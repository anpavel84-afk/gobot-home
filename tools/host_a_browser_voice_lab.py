"""HOST-A Browser Voice Lab, isolated loopback-only, one voice pipeline.

PC browser microphone -> canonical AudioChunk16k -> existing B Monika Vosk
adapter -> canonical A HostCore -> A HostAStreamingTurn -> fake OpenAI
transcription WS (NO NETWORK, NO EXPENSE) -> verified local time command ->
existing natural-voice Opus cache -> browser PCM24 sink. When the voice
cache is absent, the MOCK UI may invoke explicit browser speechSynthesis;
it is NOT represented as OpenAI/Piper speech.

Spotpear WSS input and Opus speaker are represented as separate adapters to
the same HostCore modules, but cannot be activated by this Browser Lab because
HOST-B owns the physical device. No COM3, firmware, production port/Brain.
"""
from __future__ import annotations

import asyncio
import base64
from contextlib import suppress
from datetime import datetime
import ipaddress
import json
import math
from pathlib import Path
import secrets
import sys
import time

import av
import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT.parent / "GoBotHome"
B_ROOT = ROOT.parent / "GoBotHome-wake-lab"
B_SITE = ROOT.parent / "HOST-B-lab" / ".venv" / "Lib" / "site-packages"
MODELS = ROOT.parent / "HOST-B-lab" / "models"
VOICE = ROOT / "services" / "voice"
sys.path.insert(0, str(VOICE))

from host_a_paid_budget import HostPaidTrialBudget
from host_a_browser_metered_budget import BrowserMeteredBudget
from host_a_cloud_transcribe import CloudTranscriber
from host_a_streaming_turn import HostAStreamingTurn
from host_a_wake_adapter import WakeGate, DetectorAdapter
from host_a_browser_wake_policy import BrowserWakeAdapter, address_candidate
from host_a_browser_followup_vad import (
    LocalFollowupVAD, DIALOGUE_IDLE_SECONDS)
from host_a_cloud_transcribe import FollowupPermit
from host_monika_runtime import make_owner_authorized_factory
from host_wake_core import HostCore, StreamFault
from host_wake_contract import AudioChunk
from host_a_natural_time_voice import OpenAITimeVoice
from host_local_command import classify_command, time_reply, TZ
from host_a_browser_brain_voice import BrowserBrainVoice
sys.path.insert(0, str(MAIN))
from services.brain.gobot.secrets_store import load_openai_key
from host_a_paid_budget import BudgetError
from host_a_text_journal import LocalConversationJournal

HTML = (ROOT / "tools" / "host_a_browser_voice_lab.html")
PORT = 18811
BIND = "127.0.0.1"
FRAME_SIZE = 960
PCM_BYTES = FRAME_SIZE * 2
MAX_PENDING_FRAMES = 24
MAX_ROOM_AUDIO_SEC = 600
MAX_REAL_ROOM_SEC = 600  # local WSS only; paid sessions still separately bounded
LAB_TRACE = ROOT / "run" / "host-a" / "browser-lab" / "latency_events.jsonl"
AUDIT_STAGES = {
    "ready", "wake", "cloud_connect_start", "cloud_ready",
    "cloud_partial", "cloud_commit", "cloud_final", "cloud_socket_closed",
    "cloud_verdict", "cloud_rejected",
    "followup_wait", "followup_speech_start",
    "followup_audio_commit", "followup_expired",
    "brain_start",
    "brain_first_text", "brain_final", "tts_first_audio",
    "audio_end", "playback_drained", "error", "budget_status"
}
MOCK_FINAL_TEXT = "Моника, сколько сейчас времени?"
TEST_PING = "Проверка динамиков компьютера. Это тестовый голос браузера, а не OpenAI."
app = FastAPI(title="GoBot HOST-A Browser Voice Lab", docs_url=None, redoc_url=None)
from services.brain.gobot.sophia_panel import attach_sophia_panel
attach_sophia_panel(app, MAIN)
active_lock = asyncio.Lock()
detector_factory = None


class OfflineMockWebSocket:
    """Faithful fake of official transcription events; ZERO external network."""

    def __init__(self, live_text, emit):
        self.queue = asyncio.Queue()
        self.source_text = live_text
        self.emit = emit
        self.frames = 0
        self.pcm24_bytes = 0

    async def send(self, raw):
        obj = json.loads(raw)
        event = obj.get("type")
        if event == "session.update":
            await self.queue.put(json.dumps({"type": "session.updated"}))
            await self.emit("cloud_ready", mock=True)
        elif event == "input_audio_buffer.append":
            audio = base64.b64decode(obj["audio"], validate=True)
            if len(audio) % 2 or len(audio) > 400000:
                raise RuntimeError("fake_openai_pcm_invalid")
            self.frames += 1
            self.pcm24_bytes += len(audio)
            if self.frames % 7 == 0:
                text = self.source_text()
                if text:
                    await self.queue.put(json.dumps({
                        "type": "conversation.item.input_audio_transcription.delta",
                        "item_id": "browser_mock",
                        "delta": text[:90],
                    }, ensure_ascii=False))
                    await self.emit("cloud_partial", text=text[:90], mock=True)
        elif event == "input_audio_buffer.commit":
            text = self.source_text()
            # The mock intentionally echoes the *real local Vosk hypothesis*,
            # not a fabricated OpenAI transcript.
            text = (text or "").strip()[:400]
            await self.queue.put(json.dumps({
                "type": "input_audio_buffer.committed",
                "item_id": "browser_mock",
            }))
            await self.queue.put(json.dumps({
                "type": "conversation.item.input_audio_transcription.completed",
                "item_id": "browser_mock", "transcript": text,
            }, ensure_ascii=False))
            await self.emit("cloud_final", text=text, mock=True)
        else:
            raise RuntimeError("fake_openai_protocol_message_not_supported")

    async def recv(self):
        return await self.queue.get()


class OfflineMockConnector:
    def __init__(self, text_getter, notify):
        self.socket = OfflineMockWebSocket(text_getter, notify)

    async def __aenter__(self):
        return self.socket

    async def __aexit__(self, exc_type, exc, tb):
        return False


class MockTranscriber(CloudTranscriber):
    """Reuses A's real cloud protocol/resampler; bypasses financial API calls."""
    def __init__(self, budget, text_getter, notify):
        def connector(uri, **kwargs):
            if uri != "wss://api.openai.com/v1/realtime?intent=transcription":
                raise RuntimeError("mock_wrong_endpoint")
            return OfflineMockConnector(text_getter, notify)
        super().__init__(budget, key_loader=lambda: "sk-MOCK-NOT-SENT",
                         connector=connector,
                         max_replay_samples=80000)

    async def transcribe(self, *, candidate, epoch, replay_start,
                         replay_pcm16, next_frames, max_session_seconds=30):
        # Only the official A streaming parser; zero real network/budget.
        return await self._run(
            "sk-MOCK-NOT-SENT", candidate, replay_pcm16,
            next_frames, max_session_seconds=max_session_seconds,
        )

    async def transcribe_followup(self, *, permit, conversation_id, epoch,
                                  replay_start, replay_pcm16,
                                  next_frames, max_session_seconds=20):
        # Same A streaming parser with fake WS, no OpenAI or reservation.
        # Require a real first local wake even when the continuation is mocked.
        permit.claim(epoch, conversation_id, self.clock())
        from host_a_cloud_transcribe import FollowupPosition
        return await self._run(
            "sk-MOCK-NOT-SENT",
            FollowupPosition(epoch,
                replay_start + len(replay_pcm16)//2),
            replay_pcm16, next_frames,
            max_session_seconds=max_session_seconds,
            followup=True,
        )


class BrowserAudioSink:
    """A-owned Opus24 output adapted to browser PCM16 24k playback."""
    def __init__(self, ws, emit):
        self.ws = ws
        self.emit = emit

    async def play_opus24(self, packets):
        decoder = av.CodecContext.create("opus", "r")
        converter = av.AudioResampler(format="s16", layout="mono", rate=24000)
        await self.emit("audio_start", sample_rate=24000, sample_format="pcm16le")
        total = 0
        for packet in packets:
            for frame in decoder.decode(av.Packet(packet)):
                for converted in converter.resample(frame):
                    data = converted.to_ndarray().astype("<i2", copy=False).tobytes()
                    if not data:
                        continue
                    total += len(data)
                    if total > 24000 * 2 * 6:
                        raise RuntimeError("browser_output_audio_over_limit")
                    await self.ws.send_bytes(data)
        await self.emit("audio_end", bytes_sent=total)
        return total


class BrowserVoiceSession:
    def __init__(self, websocket: WebSocket, *, factory):
        self.ws = websocket
        self.epoch = secrets.token_hex(12)
        self.factory = factory
        self.queue = asyncio.Queue(maxsize=MAX_PENDING_FRAMES)
        self.seq = 0
        self.session_started = time.monotonic()
        self.detector = None
        self.core = None
        # Browser-only 5s pre-roll: Vosk sometimes emits only a final
        # sentence after the spoken name has left the old 2s buffer.
        # Physical Spotpear keeps the original WakeGate default (2s).
        self.gate = WakeGate(capacity_samples=80000)
        self.stream = None
        self.state = "connecting"
        self.mode = "MOCK"
        # A single authenticated browser session owns one verified dialogue.
        # Cloud is NEVER left open during local idle listening.
        self.original_wake_event = None
        self.conversation_verified = False
        self.current_turn_kind = "wake"
        self.followup_vad = None
        self.followup_permit = None
        self.reply_completed = False
        self.playback_drained_seen = False
        self.pending_browser_audio_ack = False
        self.brain = None
        self.journal = None
        self.journal_failure_announced = False
        self.turn_count = 0
        self.device_id = "browser-voice-" + secrets.token_hex(6)
        self.browser_send_lock = asyncio.Lock()
        self.audit_seen = set()
        self.last_cloud_verdict = None
        self.last_text = ""
        self.latest_final = ""
        self.last_sent_text = ""
        self.last_weak_candidate = None
        self.wake_end_cursor = None
        self.response_task = None
        self.playback_active = False
        self.closing = False
        self.processing_frames = 0
        self.queue_max = 0
        self.speech_audio_samples = 0
        self.mic_peak = 0
        self.mic_rms = 0.0
        self.last_level_at = 0.0
        self.last_vosk_at = 0.0
        self.conversation_id = secrets.token_hex(8)
        # Browser-only reconciled accounting: the physical/legacy owner
        # budget remains untouched and auditable on disk.
        self.budget = BrowserMeteredBudget(
            ROOT / "run" / "host-a" / "paid-trial-20261116")
        self.voice_cache = OpenAITimeVoice(
            ROOT / "run" / "host-a" / "natural-time-voice",
            self.budget, key_loader=lambda: "")
        self.sink = BrowserAudioSink(websocket, self.emit)

    def _audit(self, kind, offset_ms, payload):
        if self.mode != "REAL" or kind not in AUDIT_STAGES:
            return
        if kind in {"cloud_ready", "cloud_connect_start", "cloud_partial",
                    "tts_first_audio", "brain_first_text"}:
            key = (self.turn_count, kind)
            if key in self.audit_seen:
                return
            self.audit_seen.add(key)
        entry = {
            "when_utc": datetime.now(TZ).isoformat(timespec="milliseconds"),
            "session": self.epoch[:12],
            "turn": self.turn_count,
            "stage": kind, "elapsed_ms": offset_ms,
            "mode": "REAL",
        }
        for name in ("setup_ms", "elapsed_ms", "audio_seconds",
                     "code", "provider", "budget_estimate_usd",
                     "first_chunk_ms", "status"):
            v = payload.get(name)
            if isinstance(v, (float, int)) and not isinstance(v, bool):
                entry[name] = round(v, 3)
            elif isinstance(v, str) and name in {"code", "provider", "status"}:
                entry[name] = v[:80]
        LAB_TRACE.parent.mkdir(parents=True, exist_ok=True)
        with LAB_TRACE.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(entry, ensure_ascii=False) + "\n")

    async def emit(self, kind, **fields):
        offset_ms = int((time.monotonic() - self.session_started) * 1000)
        self._audit(kind, offset_ms, fields)
        if self.journal is not None:
            self.journal.record(kind, offset_ms=offset_ms,
                                turn=self.turn_count, **fields)
        async with self.browser_send_lock:
            await self.ws.send_json({
                "type": kind, "timestamp_ms": offset_ms, **fields
            })

    async def cloud_event(self, kind, **fields):
        # Raw ASR/Cloud words are visible only in browser RAM, not in audit.
        await self.emit(kind, **fields)

    async def on_hello(self, obj):
        if (obj.get("type") != "hello" or
            obj.get("source") != "BROWSER_MIC" or
            obj.get("sink") != "BROWSER_AUDIO" or
            obj.get("mode") not in ("MOCK", "REAL") or
            obj.get("sample_rate") != 16000):
            await self.emit("error", code="BROWSER_MIC_AUDIO_ONLY",
                            detail="Spotpear reserved for HOST-B")
            return False
        self.mode = obj["mode"]
        if self.mode == "REAL":
            if obj.get("paid_consent") is not True:
                await self.emit("error", code="PAID_BROWSER_CONSENT_REQUIRED")
                return False
            status = await asyncio.to_thread(self.budget.status)
            if (status["reserved_seconds"] >= status["max_seconds"] or
                    status["reserved_estimated_usd"] >= status["max_estimated_usd"]):
                await self.emit("error", code="HOST_A_OWNER_LIMIT_EXHAUSTED")
                return False
            try:
                self.brain = await asyncio.to_thread(
                    BrowserBrainVoice, key_loader=load_openai_key)
            except Exception as exc:
                await self.emit("error", code=type(exc).__name__,
                                detail="Existing Brain init failed")
                return False
        try:
            self.journal = LocalConversationJournal(
                ROOT / "run" / "host-a" / "browser-lab" / "conversations",
                session=self.epoch, mode=self.mode)
            self.journal.start()
        except Exception as error:
            await self.emit("error", code="LOCAL_TEXT_JOURNAL_UNAVAILABLE",
                            detail=type(error).__name__)
            return False
        self.detector = BrowserWakeAdapter(
            await asyncio.to_thread(self.factory), self.gate)
        self.core = HostCore(
            self.detector, self.epoch,
            allowed_wake_phrases={"monika"})
        self.state = "ready"
        await self.emit("ready", source="BROWSER_MIC", sink="BROWSER_AUDIO",
                        mode=self.mode, epoch=self.epoch,
                        session_limit_seconds=(
                            MAX_REAL_ROOM_SEC if self.mode=="REAL"
                            else MAX_ROOM_AUDIO_SEC),
                        cloud_charge_usd=0 if self.mode=="MOCK" else None,
                        message=("Vosk + real OpenAI STT + existing GoBot Brain "
                                 "+ marin TTS" if self.mode=="REAL"
                                 else "Vosk REAL local speech; OpenAI FAKE protocol"))
        await self.emit(
            "journal_status",
            message="FULL_LOCAL_TEXT_JOURNAL_ENABLED",
            filename=self.journal.path.name)
        if self.mode == "REAL":
            status = await asyncio.to_thread(self.budget.status)
            await self.emit(
                "budget_report",
                status="metered_estimate_not_provider_invoice",
                budget_estimate_usd=status["reserved_estimated_usd"],
                remaining_estimated_usd=round(
                    status["max_estimated_usd"] -
                    status["reserved_estimated_usd"],5),
                historical_virtual_reserved_usd=status.get(
                    "legacy_virtual_reserved_usd"),
                historical_reconciled_estimated_usd=status.get(
                    "legacy_reconciled_estimated_usd"),
                message=("Старые резервы не списания; новая оценка основана "
                         "на измеренном аудио, токенах TTS и оценке Brain. "
                         "Источник истинного счёта — OpenAI Usage."))
        return True

    def _speech_hypothesis(self):
        hyp = getattr(self.detector.inner.inner.lab,
                      "last_hypothesis", None)
        return hyp

    async def _process_one(self, pcm):
        if self.closing:
            return
        if len(pcm) != PCM_BYTES:
            raise StreamFault("browser_frame_960_samples_required")
        received_ns = time.monotonic_ns()
        meta = {"epoch": self.epoch, "seq": self.seq,
                "sample_start": self.seq * FRAME_SIZE,
                "sample_count": FRAME_SIZE}
        samples = np.frombuffer(pcm, dtype="<i2")
        rms = math.sqrt(float(np.mean(samples.astype(np.float64) ** 2)))
        peak = int(np.max(np.abs(samples.astype(np.int32))))
        self.speech_audio_samples += FRAME_SIZE
        self.mic_peak = max(self.mic_peak, peak)
        self.mic_rms = rms
        now = time.monotonic()
        if (self.journal is not None and self.journal.failure is not None
                and not self.journal_failure_announced):
            self.journal_failure_announced = True
            await self.emit("error", code="FULL_TEXT_JOURNAL_INCOMPLETE",
                            detail=self.journal.failure)
        if now - self.last_level_at >= 0.25:
            await self.emit("signal", peak_dbfs=round(
                20 * math.log10(max(peak, 1) / 32768), 1),
                rms_dbfs=round(
                    20 * math.log10(max(rms, .01) / 32768), 1),
                processed_frames=self.processing_frames,
                queue_depth=self.queue.qsize(),
                queue_peak=self.queue_max)
            self.last_level_at = now
        if self.stream is not None and self.stream.active:
            self.stream.offer(AudioChunk(
                pcm, self.epoch, self.core.sample_cursor, received_ns))
        if (self.playback_active or self.core.local_reply_pending
                or self.followup_vad is not None
                or (self.stream is not None
                    and self.current_turn_kind == "followup")):
            self.detector.suppress_events = True
        else:
            self.detector.suppress_events = False
        events = await asyncio.to_thread(
            self.core.feed, meta, pcm,
            received_monotonic_ns=received_ns)
        self.seq += 1
        self.processing_frames += 1
        hyp = self._speech_hypothesis()
        if hyp is not None:
            value = str(hyp.text or "").strip()
            if value:
                weak = address_candidate(value)
                if weak and weak[0] == "weak" and (
                        weak[1] != self.last_weak_candidate
                        or bool(hyp.endpoint)):
                    self.last_weak_candidate = weak[1]
                    remaining = max(
                        0, self.detector.matcher.weak_limit -
                        self.detector.matcher.weak_total)
                    await self.emit(
                        "weak_candidate_seen", text=value,
                        word=weak[1], status=(
                            "session_weak_limit_reached" if remaining == 0
                            else "local_audio_verification_candidate"),
                        remaining_attempts=remaining)
                if hyp.endpoint or not weak:
                    self.last_weak_candidate = None
                if hyp.endpoint:
                    self.latest_final = value
                self.last_text = value
                if self.journal is not None:
                    self.journal.record_vosk(
                        text=value, final=bool(hyp.endpoint),
                        offset_ms=(now-self.session_started)*1000,
                        sample_cursor=self.core.sample_cursor,
                        frame_seq=self.seq,
                        rms_dbfs=round(
                            20*math.log10(max(rms, .01)/32768), 1),
                        turn=self.turn_count)
                if ((value != self.last_sent_text
                     and now - self.last_vosk_at >= .15)
                        or hyp.endpoint):
                    await self.emit(
                        "asr", text=value,
                        stage="final" if hyp.endpoint else "partial",
                        engine="vosk-small-ru-0.22", actual=True)
                    self.last_sent_text = value
                    self.last_vosk_at = now
        if self.followup_vad is not None:
            await self._evaluate_followup_audio(
                pcm=bytes(pcm), index=self.core.sample_cursor-FRAME_SIZE,
                now=now, rms=rms)
        for event in events:
            if event["event"] == "wake" and event.get("source") == "host_wake":
                self.wake_end_cursor = self.core.sample_cursor
                self.last_text = self.last_text or "Моника"
                self.turn_count += 1
                self.current_turn_kind = "wake"
                self.original_wake_event = self.detector.last_wake_event
                self.reply_completed = False
                self.playback_drained_seen = False
                self.conversation_verified = False
                if self.journal is not None:
                    self.journal.record(
                        "wake_candidate", offset_ms=(
                            time.monotonic()-self.session_started)*1000,
                        turn=self.turn_count,
                        text=str(hyp.text) if hyp is not None else self.last_text,
                        engine="vosk-small-ru-0.22",
                        sample_cursor=self.core.sample_cursor,
                        reason=str(self.detector.last_candidate_kind or ""),
                        model=str(self.detector.last_candidate_token or ""))
                if self.mode == "REAL":
                    factory = lambda: CloudTranscriber(
                        self.budget, key_loader=load_openai_key,
                        event_hook=self.cloud_event,
                        max_replay_samples=80000)
                else:
                    factory = lambda: MockTranscriber(
                        self.budget,
                        text_getter=lambda: self.latest_final or self.last_text,
                        notify=self.emit,
                    )
                self.stream = HostAStreamingTurn(
                    self.gate, self.budget,
                    key_loader=load_openai_key if self.mode=="REAL"
                               else (lambda: ""),
                    voice_cache=self.voice_cache,
                    client_factory=factory,
                    max_frames=96, max_cloud_seconds=20)
                await self.stream.on_wake(event)
                await self.emit(
                    "candidate_notice",
                    word=str(self.detector.last_candidate_token or "моника"),
                    strength=str(self.detector.last_candidate_kind or "strong"),
                    status=("real_audio_cloud_verification" if
                            self.mode == "REAL" else "free_mock_verification"))
                self.state = "listening"
                await self.emit("wake", phrase="Моника",
                                mode=self.mode, local=True)
                await self.emit("state", value=self.state)
        if (self.stream and self.stream.active and self.core.active
                and self.wake_end_cursor is not None):
            elapsed = self.core.sample_cursor - self.wake_end_cursor
            endpoint = bool(hyp and hyp.endpoint)
            if ((endpoint and elapsed >= 4800) or elapsed >= 128000):
                await self.stream.finish()
                utterance = self.core.finish_input()
                if utterance:
                    utterance.clear()
                self.core.local_reply_pending = True
                self.state = "thinking"
                await self.emit("state", value="thinking")
                self.response_task = asyncio.create_task(self._finish_reply())

    def _cloud_transcriber_factory(self):
        # Same official CloudTranscriber as initial Monika trigger;
        # only the permit and turn segmentation differ.
        if self.mode == "REAL":
            return lambda: CloudTranscriber(
                self.budget, key_loader=load_openai_key,
                event_hook=self.cloud_event,
                max_replay_samples=80000)
        return lambda: MockTranscriber(
            self.budget,
            text_getter=lambda: self.latest_final or self.last_text,
            notify=self.emit,
        )

    async def _arm_followup_after_playback(self):
        """Reopen local mic-only dialogue; no cloud connection on standby."""
        if (self.closing or not self.reply_completed
                or not self.playback_drained_seen
                or self.original_wake_event is None
                or not self.conversation_verified):
            return False
        # One local verified wake anchors every subsequent dialogue turn.
        # Time-limited one-shot permit is minted only after human playback ACK.
        now = time.monotonic()
        expires = now + DIALOGUE_IDLE_SECONDS
        self.followup_permit = FollowupPermit(
            initial_wake=self.original_wake_event,
            conversation_id=self.conversation_id,
            expires_monotonic=expires)
        self.followup_vad = LocalFollowupVAD(
            deadline=expires, armed_at=now,
            sample_cursor=self.core.sample_cursor)
        self.state = "followup"
        await self.emit(
            "followup_wait", idle_seconds=DIALOGUE_IDLE_SECONDS,
            message="Speak naturally without repeating Monika",
            provider="local_pcm_vad")
        await self.emit("state", value=self.state)
        return True

    async def _evaluate_followup_audio(self, *, pcm, index, now, rms):
        vad = self.followup_vad
        if vad is None:
            return
        choice = vad.feed(pcm=pcm, index=index, now=now, rms=rms)
        if choice is None:
            return
        if choice.kind == "expired":
            self.followup_vad = None
            self.followup_permit = None
            self.original_wake_event = None
            self.conversation_verified = False
            self.current_turn_kind = "wake"
            self.state = "ready"
            self.detector.reset()
            await self.emit(
                "followup_expired", status="idle_timeout",
                idle_seconds=DIALOGUE_IDLE_SECONDS)
            await self.emit("state", value="ready")
            return
        if choice.kind == "start":
            permit = self.followup_permit
            if permit is None:
                raise RuntimeError("followup_local_speech_without_permit")
            self.turn_count += 1
            self.current_turn_kind = "followup"
            self.reply_completed = False
            self.playback_drained_seen = False
            self.pending_browser_audio_ack = False
            self.latest_final = ""
            self.last_text = ""
            self.followup_permit = None  # Claim exactly once.
            self.stream = HostAStreamingTurn(
                self.gate, self.budget,
                key_loader=load_openai_key if self.mode=="REAL"
                           else (lambda: ""),
                client_factory=self._cloud_transcriber_factory(),
                max_frames=96, max_cloud_seconds=20)
            await self.stream.on_followup(
                permit=permit, conversation_id=self.conversation_id,
                epoch=self.epoch, replay_start=choice.replay_start,
                replay_pcm16=choice.replay_pcm)
            self.state = "listening"
            await self.emit(
                "followup_speech_start", source="local_pcm_vad",
                sample_cursor=choice.replay_start,
                rms_dbfs=round(20*math.log10(max(rms,.01)/32768),1),
                mode=self.mode,
                message="Continue without wake name")
            await self.emit("state", value="listening")
            return
        if choice.kind in {"commit_silence","commit_max_duration"}:
            if self.stream is None or self.current_turn_kind != "followup":
                raise RuntimeError("followup_commit_without_active_turn")
            await self.stream.finish()
            self.followup_vad = None
            self.core.local_reply_pending = True
            self.state = "thinking"
            await self.emit(
                "followup_audio_commit", reason=choice.kind,
                source="local_pcm_vad")
            await self.emit("state", value="thinking")
            self.response_task = asyncio.create_task(self._finish_reply())

    async def _finish_real_reply(self):
        from host_a_browser_real_controller import finish_real_reply
        await finish_real_reply(self)

    async def _finish_reply(self):
        try:
            if self.mode == "REAL":
                await self._finish_real_reply()
                return
            result = await self.stream.reply()
            if result:
                self.conversation_verified = True  # MOCK only, zero paid.
                self.reply_completed = True
                self.playback_active = True
                self.state = "speaking"
                await self.emit("state", value="speaking")
                self.core.playback(True, self.core.output_epoch)
                await self.sink.play_opus24(result)
                await self.emit("text_reply", text="Голос OpenAI из кэша")
                return
            await self.emit("mock_note", message=(
                "Реальная локальная гипотеза Vosk передана в имитацию "
                "OpenAI STT. Если время распознано, но нет голосового "
                "кэша, платный TTS не запускается."))
            await self.emit("mock_speaker", text=TEST_PING)
            self.conversation_verified = True  # MOCK only.
            self.reply_completed = True
            self.state = "speaking"
            await self.emit("state", value="speaking")
        except Exception as exc:
            await self.emit("error", code=type(exc).__name__,
                            detail="Mock streaming-first response failed")
            self.state = "ready"
            await self.emit("state", value="ready")
        finally:
            self.core.local_reply_pending = False
            self.stream = None
            self.wake_end_cursor = None
            self.response_task = None
            if self.pending_browser_audio_ack and self.reply_completed:
                self.pending_browser_audio_ack = False
                await self._arm_followup_after_playback()

    async def handle_control(self, obj):
        kind = obj.get("type")
        if kind == "stop":
            self.followup_vad = None
            self.followup_permit = None
            self.conversation_verified = False
            self.closing = True
            return False
        if kind == "speaker_test":
            await self.emit("mock_speaker", text=TEST_PING)
        elif kind == "playback_drained":
            if self.playback_drained_seen:
                return True  # Avoid re-arming twice on duplicate client ACK.
            if self.playback_active:
                self.core.playback(False, self.core.output_epoch)
            self.playback_active = False
            self.playback_drained_seen = True
            await self.emit("playback_drained", status="confirmed_by_browser")
            if self.journal is not None:
                self.journal.summarize_turn(self.turn_count)
            if (self.reply_completed and
                    (self.response_task is None
                     or self.response_task.done())):
                await self._arm_followup_after_playback()
            else:
                self.pending_browser_audio_ack = True
                self.state = "answer_finishing"
                await self.emit("state", value=self.state)
        elif kind == "cancel":
            self.followup_vad = None
            self.followup_permit = None
            self.conversation_verified = False
            self.original_wake_event = None
            if self.stream:
                await self.stream.cancel()
            if self.core.active:
                self.core.stop()
                self.core.stop_pending = None
            self.core.local_reply_pending = False
            self.playback_drained_seen = False
            self.state = "ready"
            await self.emit("state", value="ready")
        else:
            await self.emit("error", code="UNSUPPORTED_CONTROL")
        return True

    async def run(self):
        incoming = asyncio.create_task(self._receive())
        processing = asyncio.create_task(self._process())
        try:
            done, pending = await asyncio.wait(
                [incoming, processing], return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                try:
                    task.result()
                except WebSocketDisconnect:
                    pass
                except asyncio.CancelledError:
                    pass
                except Exception as exc:
                    with suppress(Exception):
                        await self.emit("error", code=type(exc).__name__,
                                        detail=str(exc)[:100])
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
        finally:
            self.closing = True
            if self.stream:
                await self.stream.cancel()
            if self.response_task is not None:
                self.response_task.cancel()
                await asyncio.gather(self.response_task, return_exceptions=True)
            if self.core is not None:
                self.core.close()
            self.gate.clear()
            if self.brain is not None:
                await asyncio.to_thread(self.brain.close)
                self.brain = None
            if self.journal is not None:
                await self.journal.close()
                self.journal = None

    async def _receive(self):
        while time.monotonic() - self.session_started < (
                MAX_REAL_ROOM_SEC if self.mode=="REAL"
                else MAX_ROOM_AUDIO_SEC):
            msg = await self.ws.receive()
            if msg["type"] == "websocket.disconnect":
                return
            if msg.get("bytes") is not None:
                if self.state == "connecting":
                    raise RuntimeError("hello_required_before_pcm")
                if self.queue.full():
                    await self.emit("error", code="browser_pcm_queue_overflow")
                    return
                self.queue.put_nowait(msg["bytes"])
                self.queue_max = max(self.queue_max, self.queue.qsize())
            elif msg.get("text") is not None:
                obj = json.loads(msg["text"])
                if self.state == "connecting":
                    if not await self.on_hello(obj):
                        return
                else:
                    if not await self.handle_control(obj):
                        return

    async def _process(self):
        while not self.closing and (
                time.monotonic() - self.session_started <
                (MAX_REAL_ROOM_SEC if self.mode=="REAL"
                 else MAX_ROOM_AUDIO_SEC)):
            frame = await self.queue.get()
            try:
                await self._process_one(frame)
            finally:
                self.queue.task_done()


@app.get("/")
async def home():
    return HTMLResponse(HTML.read_text(encoding="utf-8"),
                        headers={"Cache-Control": "no-store"})


@app.get("/health")
async def health():
    return {
        "status": "ready", "app": "HOST-A Browser Voice Lab",
        "mock_only": False, "real_mode_requires_explicit_paid_consent": True,
        "real_brain": "existing GoBot Brain isolated temporary DB",
        "voice_pipeline": "HostCore/Monika/CloudTranscriber",
        "browser_source": "BROWSER_MIC",
        "browser_sink": "BROWSER_AUDIO",
        "spotpear_status": "RESERVED_FOR_HOST_B",
        "openai_cloud_calls": "only_after_local_wake_and_explicit_owner_consent",
        "budget_cap_usd": 3.0, "browser_port": PORT,
    }


@app.websocket("/ws")
async def voice_websocket(ws: WebSocket):
    ip = ipaddress.ip_address(ws.client.host if ws.client else "0.0.0.0")
    origin = ws.headers.get("origin", "")
    # Tailscale Serve terminates HTTPS and proxies the authenticated tailnet
    # request into this isolated loopback-only server. Reject other origins.
    allowed_origins = (
        "http://127.0.0.1:18811", "http://localhost:18811",
        "https://plan.tailffc57c.ts.net",
    )
    if (not ip.is_loopback or origin not in allowed_origins):
        await ws.close(code=1008)
        return
    if active_lock.locked():
        await ws.accept()
        await ws.send_json({"type": "error", "code": "ANOTHER_BROWSER_LAB_ACTIVE"})
        await ws.close(code=1013)
        return
    async with active_lock:
        await ws.accept()
        lab = BrowserVoiceSession(ws, factory=detector_factory)
        try:
            await lab.run()
        finally:
            with suppress(Exception):
                await ws.close()


def main():
    import uvicorn
    global detector_factory
    print("BROWSER_LAB_PREFLIGHT_MODELS", flush=True)
    detector_factory = make_owner_authorized_factory(
        B_ROOT, MODELS, B_SITE)
    from host_wake_contract import AudioChunk
    sample = detector_factory()
    for n in range(5):
        sample.feed_chunk(AudioChunk(bytes(1920), "preflight",
                                     n * 960, time.monotonic_ns()))
    sample.reset()
    print("BROWSER_LAB_MODEL_AND_SHARED_PIPELINE_PASS", flush=True)
    print(f"BROWSER_VOICE_LAB_URL=http://{BIND}:{PORT}/", flush=True)
    # Do not trust X-Forwarded-For for WebSocket client IP. Tailscale Serve
    # connects through local loopback; origin ACL remains exact HTTPS tailnet.
    uvicorn.run(app, host=BIND, port=PORT, log_level="warning",
                access_log=False, proxy_headers=False)


if __name__ == "__main__":
    main()
