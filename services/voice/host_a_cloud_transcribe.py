"""HOST-A bounded realtime transcription of one locally authorized Spotpear turn.

The remote API is NEVER opened on standby. Strict HOST wake, epoch, sample
position, session duration and a persistent Owner expense reservation precede
connection. Actual transcript data lives only in RAM. A separate Brain router
must enforce confirmed address + ACL before taking any action.
"""
from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass, field
import json
import math
import re
import time
from typing import AsyncIterable, Callable

import numpy as np
from websockets.asyncio.client import connect as real_connect

from host_wake_contract import AudioChunk, WakeEvent
from host_a_paid_budget import HostPaidTrialBudget, BudgetError

URI = "wss://api.openai.com/v1/realtime?intent=transcription"
MODEL = "gpt-live-transcribe"
INPUT_RATE = 16000
CLOUD_RATE = 24000
MAX_AUDIO_SECONDS = 15
MAX_REPLAY_SAMPLES = INPUT_RATE * 2
MAX_BROWSER_REPLAY_SAMPLES = INPUT_RATE * 5


class TranscriptionFault(RuntimeError):
    pass


@dataclass(slots=True)
class FollowupPermit:
    """One-time browser-only continuation, based on actual verified local wake."""
    initial_wake: WakeEvent
    conversation_id: str
    expires_monotonic: float
    consumed: bool = False

    def claim(self, epoch: str, conversation_id: str, now: float):
        if (not isinstance(self.initial_wake, WakeEvent)
                or self.initial_wake.phrase_id != "monika"
                or self.initial_wake.stream_epoch != epoch
                or self.conversation_id != conversation_id
                or self.consumed
                or not isinstance(now, (float, int))
                or now > self.expires_monotonic):
            raise TranscriptionFault("followup_requires_live_verified_dialogue")
        self.consumed = True


@dataclass(frozen=True, slots=True)
class FollowupPosition:
    stream_epoch: str
    end_sample_index: int


@dataclass(frozen=True)
class CloudResult:
    verdict: str
    question: str | None = field(repr=False)
    transcript: str = field(repr=False)
    first_partial_ms: float | None = None
    setup_ms: float | None = None
    final_ms: float | None = None
    audio_seconds: float = 0.0
    model: str = MODEL


def config_update(*, followup=False):
    return {
        "type": "session.update",
        "session": {
            "type": "transcription",
            "audio": {"input": {
                "format": {"type": "audio/pcm", "rate": CLOUD_RATE},
                "transcription": {
                    "model": MODEL,
                    "keywords": [] if followup else ["Моника"],
                    "languages": ["ru"],
                    "delay": "low",
                },
                "turn_detection": None,
            }},
        },
    }


def _resample_16_to_24(pcm16: bytes) -> bytes:
    if not isinstance(pcm16, bytes) or len(pcm16) % 2 or not pcm16:
        raise TranscriptionFault("invalid_input_pcm")
    samples = np.frombuffer(pcm16, dtype="<i2")
    # Stable exact 3:2 conversion, 960 source samples -> 1440 output samples.
    # Future quality tuning should use a stateful low-pass resampler, but this
    # implementation never changes duration or silently drops positions.
    count = len(samples) * 3 // 2
    if len(samples) % 2:
        raise TranscriptionFault("input_16k_samples_must_be_even")
    positions = np.arange(count, dtype=np.float64) * (2.0 / 3.0)
    out = np.interp(positions, np.arange(len(samples)), samples)
    return np.rint(out).clip(-32768, 32767).astype("<i2").tobytes()


def verify_address(transcript: str) -> tuple[str, str | None]:
    """Three-valued cloud verification; no speculative action on uncertainty."""
    if not isinstance(transcript, str) or len(transcript) > 500:
        return "UNCERTAIN", None
    words = re.findall(r"[а-яё]+", transcript.casefold())
    if not words:
        return "UNCERTAIN", None
    from host_a_browser_wake_policy import address_candidate
    checked = address_candidate(transcript)
    if checked is not None and checked[0] == "strong":
        # Cloud independently hears the canonical name. Short salutations
        # like "Окей, Моника" are allowed; ordinary third-person mentions
        # and weak Vosk aliases are not treated as verification.
        idx = checked[2]
        question = " ".join(words[idx + 1:]).strip()
        if not question or len(question) > 280:
            return "UNCERTAIN", None
        return "CONFIRMED", question
    if words[0] in {"моник", "монитор", "моня", "модница", "гобот"}:
        return "REJECTED", None
    return "UNCERTAIN", None


class CloudTranscriber:
    def __init__(self, budget: HostPaidTrialBudget, *, key_loader: Callable[[], str],
                 connector=real_connect, clock=time.monotonic, event_hook=None,
                 max_replay_samples=MAX_REPLAY_SAMPLES):
        if (type(max_replay_samples) is not int or
                not MAX_REPLAY_SAMPLES <= max_replay_samples
                <= MAX_BROWSER_REPLAY_SAMPLES):
            raise ValueError("stt_replay_capacity_not_authorized")
        self.max_replay_samples = max_replay_samples
        self.budget = budget
        self.key_loader = key_loader
        self.connector = connector
        self.clock = clock
        self.event_hook = event_hook

    async def _notify(self, stage, **values):
        if self.event_hook is not None:
            await self.event_hook(stage, **values)

    async def transcribe(self, *, candidate: WakeEvent, epoch: str,
                         replay_start: int, replay_pcm16: bytes,
                         next_frames: AsyncIterable[AudioChunk],
                         max_session_seconds: int = 90) -> CloudResult:
        if (not isinstance(candidate, WakeEvent) or candidate.phrase_id != "monika"
                or candidate.stream_epoch != epoch or not epoch):
            raise TranscriptionFault("cloud_requires_local_monika_wake")
        if not isinstance(replay_pcm16, bytes) or len(replay_pcm16) % 2:
            raise TranscriptionFault("replay_pcm_invalid")
        replay_samples = len(replay_pcm16) // 2
        if (not isinstance(replay_start, int) or replay_start < 0
                or not 0 < replay_samples <= self.max_replay_samples
                or replay_start + replay_samples != candidate.end_sample_index):
            raise TranscriptionFault("replay_position_invalid")
        if type(max_session_seconds) is not int or not 5 <= max_session_seconds <= 180:
            raise TranscriptionFault("session_bound_invalid")
        # Financial reservation is the only permitted entry to a paid session.
        reservation = self.budget.reserve(MODEL, max_session_seconds,
                                          local_wake_confirmed=True)
        started = self.clock()
        result = "FAILED"
        delivered_audio_seconds = None
        try:
            secret = self.key_loader()
            if not isinstance(secret, str) or not secret.startswith("sk-"):
                raise TranscriptionFault("api_key_unavailable")
            response = await asyncio.wait_for(self._run(
                secret, candidate, replay_pcm16, next_frames,
                max_session_seconds=max_session_seconds,
            ), timeout=max_session_seconds)
            # _run() returns only after the WebSocket close handshake; measure
            # this separately from the actual final STT transcript event.
            await self._notify("cloud_socket_closed")
            delivered_audio_seconds = response.audio_seconds
            result = "COMPLETE"
            return response
        except asyncio.TimeoutError as exc:
            result = "TIMEOUT"
            raise TranscriptionFault("paid_session_wall_timeout") from exc
        except asyncio.CancelledError:
            result = "CANCELLED"
            raise
        finally:
            elapsed = max(0.0, self.clock() - started)
            kwargs={"elapsed_seconds":elapsed,"result":result}
            if getattr(self.budget,"supports_metered_settlement",False):
                kwargs["audio_seconds"]=delivered_audio_seconds
            self.budget.finish(reservation, **kwargs)

    async def transcribe_followup(self, *, permit: FollowupPermit,
                                  conversation_id: str, epoch: str,
                                  replay_start: int, replay_pcm16: bytes,
                                  next_frames: AsyncIterable[AudioChunk],
                                  max_session_seconds: int = 20) -> CloudResult:
        """One finite paid STT inside a previously cloud-verified dialogue.

        A new name is NOT required while the short local dialogue window is
        open. One-use permit + local speech onset + existing Owner budget
        are ALL required. This is never a background cloud listener.
        """
        if not isinstance(permit, FollowupPermit):
            raise TranscriptionFault("missing_real_wake_continuation_permit")
        if (type(max_session_seconds) is not int
                or not 5 <= max_session_seconds <= 20):
            raise TranscriptionFault("unbounded_followup_cloud_turn")
        if (not isinstance(replay_pcm16, bytes) or len(replay_pcm16)%2
                or not 0 < len(replay_pcm16) <= 32000 * 2):
            raise TranscriptionFault("invalid_followup_audio_preroll")
        if (type(replay_start) is not int or replay_start < 0
                or not epoch or replay_start % 960):
            raise TranscriptionFault("invalid_followup_sample_position")
        permit.claim(epoch, conversation_id, self.clock())
        end = replay_start + len(replay_pcm16)//2
        position = FollowupPosition(epoch, end)
        # Existing persistent grant is charged conservatively; the initial
        # verified local wake underlies this finite, local-VAD continuation.
        booking = self.budget.reserve(
            MODEL, max_session_seconds, local_wake_confirmed=True)
        started = self.clock()
        status = "FAILED"
        delivered_audio_seconds = None
        try:
            key = self.key_loader()
            if not isinstance(key, str) or not key.startswith("sk-"):
                raise TranscriptionFault("followup_api_key_unavailable")
            result = await asyncio.wait_for(
                self._run(key, position, replay_pcm16, next_frames,
                          max_session_seconds=max_session_seconds,
                          followup=True), timeout=max_session_seconds)
            await self._notify("cloud_socket_closed")
            delivered_audio_seconds = result.audio_seconds
            status = "COMPLETE"
            return result
        except asyncio.CancelledError:
            status = "CANCELLED"
            raise
        except asyncio.TimeoutError as exc:
            status = "TIMEOUT"
            raise TranscriptionFault("followup_cloud_wall_timeout") from exc
        finally:
            kwargs={
                "elapsed_seconds":max(0.0,self.clock()-started),
                "result":status,
            }
            if getattr(self.budget,"supports_metered_settlement",False):
                kwargs["audio_seconds"]=delivered_audio_seconds
            self.budget.finish(booking,**kwargs)

    async def _run(self, secret, candidate, replay_pcm16, next_frames,
                   *, max_session_seconds, followup=False):
        opened_at = self.clock()
        await self._notify("cloud_connect_start")
        headers = {"Authorization": "Bearer " + secret}
        # No log of Authorization; avoid proxies reading key/audio.
        async with self.connector(
            URI, additional_headers=headers, proxy=None,
            open_timeout=7, close_timeout=.25,
            max_size=65536, max_queue=32, compression=None,
        ) as ws:
            ready = asyncio.get_running_loop().create_future()
            completed = asyncio.get_running_loop().create_future()
            error = asyncio.get_running_loop().create_future()
            seen_commit_item = None
            pending_final = {}
            markers = {"partial": None, "ready": None}
            deltas = []
            async def receiver():
                nonlocal seen_commit_item
                while True:
                    raw = await ws.recv()
                    obj = json.loads(raw)
                    kind = obj.get("type")
                    if kind == "session.updated":
                        if not ready.done():
                            markers["ready"] = self.clock()
                            await self._notify(
                                "cloud_ready",
                                setup_ms=round((markers["ready"]-opened_at)*1000,2))
                            ready.set_result(True)
                    elif kind == "input_audio_buffer.committed":
                        seen_commit_item = obj.get("item_id")
                        if seen_commit_item in pending_final and not completed.done():
                            completed.set_result(pending_final[seen_commit_item])
                    elif kind == "conversation.item.input_audio_transcription.delta":
                        if markers["partial"] is None:
                            markers["partial"] = self.clock()
                        delta = obj.get("delta", "")[:250]
                        await self._notify("cloud_partial", text=delta,
                            elapsed_ms=round((self.clock()-opened_at)*1000,2))
                        if len(deltas) < 300:
                            deltas.append(delta)
                    elif kind == "conversation.item.input_audio_transcription.completed":
                        item = obj.get("item_id")
                        phrase = obj.get("transcript", "")
                        if not isinstance(phrase, str) or len(phrase) > 500:
                            raise TranscriptionFault("final_transcript_outside_bounds")
                        pending_final[item] = phrase
                        await self._notify("cloud_final", text=phrase,
                            elapsed_ms=round((self.clock()-opened_at)*1000,2))
                        if seen_commit_item == item and not completed.done():
                            completed.set_result(phrase)
                    elif kind in ("error", "conversation.item.input_audio_transcription.failed"):
                        if not error.done():
                            error.set_result(kind)

            reader = asyncio.create_task(receiver())
            async def wait_or_error(future, seconds):
                done, _ = await asyncio.wait([future, error, reader],
                                             timeout=seconds,
                                             return_when=asyncio.FIRST_COMPLETED)
                if error in done or reader in done:
                    raise TranscriptionFault("cloud_protocol_error_or_close")
                if future not in done:
                    raise TranscriptionFault("cloud_response_timeout")
                return future.result()

            async def send(message):
                await asyncio.wait_for(ws.send(json.dumps(message,
                    ensure_ascii=False, separators=(",", ":"))), 3)

            samples_sent = 0
            cursor = candidate.end_sample_index
            try:
                await send(config_update(followup=followup))
                await wait_or_error(ready, 8)
                async def push(pcm):
                    nonlocal samples_sent
                    samples_sent += len(pcm) // 2
                    if samples_sent > INPUT_RATE * MAX_AUDIO_SECONDS:
                        raise TranscriptionFault("cloud_capture_limit_15s")
                    await send({"type": "input_audio_buffer.append",
                                "audio": base64.b64encode(
                                    _resample_16_to_24(pcm)).decode("ascii")})

                # Start with the exact locally verified pre-roll and continue
                # at its sample cursor, with no silent skip/overlap.
                await push(replay_pcm16)
                async for frame in next_frames:
                    if (not isinstance(frame, AudioChunk) or frame.stream_epoch != candidate.stream_epoch
                            or frame.sample_index != cursor):
                        raise TranscriptionFault("cloud_stale_or_noncontiguous_frame")
                    cursor = frame.end_sample_index
                    await push(frame.pcm_s16le)
                await send({"type": "input_audio_buffer.commit"})
                await self._notify("cloud_commit", audio_seconds=
                    round(samples_sent/INPUT_RATE,3))
                final = await wait_or_error(completed, max(1, min(20, max_session_seconds)))
                if followup:
                    # A valid short in-dialogue token, not a new name claim.
                    # Preserve exact source transcript, trim optional address.
                    transcript = final.strip()
                    if not transcript or len(transcript) > 300:
                        verdict, question = "UNCERTAIN", None
                    else:
                        checked, maybe_question = verify_address(transcript)
                        question = maybe_question if checked == "CONFIRMED" else transcript
                        verdict = "FOLLOWUP"
                else:
                    verdict, question = verify_address(final)
                return CloudResult(
                    verdict=verdict, question=question, transcript=final,
                    setup_ms=round((markers["ready"] - opened_at) * 1000, 2),
                    first_partial_ms=(
                        round((markers["partial"] - opened_at) * 1000, 2)
                        if markers["partial"] is not None else None),
                    final_ms=round((self.clock() - opened_at) * 1000, 2),
                    audio_seconds=round(samples_sent / INPUT_RATE, 3),
                )
            finally:
                reader.cancel()
                await asyncio.gather(reader, return_exceptions=True)
