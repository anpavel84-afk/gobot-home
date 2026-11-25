"""Owner-consented full local *text* conversation journal for HOST-A Browser Lab.

Records every distinct Vosk hypothesis, Cloud STT delta/final, verified Brain
input, Brain stream/done, statuses, and timing. No raw PCM/Opus, API tokens,
authentication headers, secrets or file paths from user speech.

The writer uses a bounded queue and a dedicated asynchronous disk task, so
expensive disk writes never block 60-ms microphone frames. On overflow or
I/O failure, completeness is marked FALSE: never pretend to have a full log.
Only PLAN-local filesystem; no browser endpoint exposes these records.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path

SCHEMA = "gobot_host_a_full_text_journal_v1"
MAX_QUEUE = 8192
MAX_FILE_BYTES = 24 * 1024 * 1024
TEXT_FIELDS = {"text", "question", "transcript", "delta", "message", "detail"}
# Never persist arbitrary event keys (could accidentally contain keys/tokens).
SAFE_FIELDS = {
    "text", "question", "transcript", "delta", "message", "detail",
    "source", "sink", "mode", "engine", "provider", "model", "status",
    "route", "reason", "filename", "word", "strength",
    "remaining_attempts", "remaining_estimated_usd",
    "code", "voice", "tts_voice", "tts_model", "chat_model",
    "audio_seconds", "setup_ms", "elapsed_ms", "first_chunk_ms",
    "total_ms", "sample_index", "sample_cursor", "frame_seq",
    "peak_dbfs", "rms_dbfs", "queue_depth", "queue_peak",
    "bytes_sent", "local", "mock", "actual", "sample_rate",
    "processed_frames", "budget_estimate_usd", "remaining_estimated_usd",
    "reserved_seconds", "remaining_seconds", "session_limit_seconds",
    "verdict",
}
# Prohibit any raw audio/base64 by both field-name allow-list and data type.
SUMMARY_STAGES = {
    "wake", "cloud_connect_start", "cloud_ready", "cloud_commit",
    "cloud_socket_closed", "followup_wait", "followup_speech_start",
    "followup_audio_commit", "followup_expired",
    "cloud_partial", "cloud_final", "cloud_verdict", "cloud_rejected",
    "brain_question", "brain_start", "brain_first_text", "brain_final",
    "tts_first_audio", "audio_end", "playback_drained", "error",
}
FINAL_STAGES = {"cloud_rejected", "playback_drained"}


def _stamp():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _int_or_none(v):
    return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


class LocalConversationJournal:
    def __init__(self, folder: str | Path, *, session: str, mode: str):
        if mode not in {"MOCK", "REAL"}:
            raise ValueError("journal_invalid_lab_mode")
        if not (len(session) == 24 and all(c in "0123456789abcdef" for c in session)):
            raise ValueError("invalid_journal_session_identity")
        self.folder = Path(folder)
        self.session = session
        self.mode = mode
        self.created_utc = _stamp()
        self.queue = asyncio.Queue(maxsize=MAX_QUEUE)
        self.task = None
        self.failure = None
        self.dropped = 0
        self.persisted = 0
        self.closed = False
        self.frames = 0
        self.turns = {}
        self.previous_vosk = ""
        self.previous_endpoint = False
        self.last_final_text = ""
        self._disk_bytes = 0
        # ACL inherited from the PLAN user's private profile. Never web-served.
        self.folder.mkdir(parents=True, exist_ok=True)
        self.path = self.folder / (
            "session-" + self.created_utc[:19].replace(":", "-") + "-" +
            session + ".jsonl"
        )
        # Fail closed on startup if a local file cannot be created.
        with self.path.open("x", encoding="utf-8", newline="\n") as fp:
            header = {
                "schema": SCHEMA, "at_utc": self.created_utc,
                "session": self.session, "mode": self.mode,
                "stage": "session_start", "turn": 0,
                "includes_full_text": True, "raw_audio_saved": False,
                "api_keys_saved": False, "storage": "PLAN_LOCAL_ONLY",
            }
            raw = json.dumps(header, ensure_ascii=False)
            fp.write(raw + "\n")
            self._disk_bytes = len((raw + "\n").encode("utf-8"))
        self.persisted += 1

    def start(self):
        if self.task is None:
            self.task = asyncio.create_task(
                self._writer(), name="host-a-owner-local-text-journal"
            )

    @staticmethod
    def _safe_payload(fields):
        clean = {}
        for key, value in fields.items():
            if key not in SAFE_FIELDS:
                continue
            if isinstance(value, str):
                # 32k chars per field comfortably exceeds all bounded
                # model/user text in this experimental audio flow.
                clean[key] = value[:32768]
            elif value is None or isinstance(value, (bool, int, float)):
                clean[key] = value
        return clean

    def record(self, event_type: str, *, offset_ms: float | int,
               turn: int, **fields):
        # 'stage' in the WebSocket payload can be "partial" or "final".
        # The canonical journal event kind is a separate positional argument.
        # Naming it event_type avoids TypeError on every Vosk ASR message.
        if self.closed:
            return
        if not isinstance(event_type, str) or not 1 <= len(event_type) <= 90:
            raise ValueError("invalid_journal_event")
        if not isinstance(turn, int) or turn < 0:
            raise ValueError("invalid_journal_turn")
        event = {
            "schema": SCHEMA,
            "at_utc": _stamp(),
            "session": self.session,
            "turn": turn,
            "stage": event_type,
            "since_session_ms": round(float(offset_ms), 3),
            "mode": self.mode,
            **self._safe_payload(fields),
        }
        self._update_summary(event)
        try:
            self.queue.put_nowait(event)
        except asyncio.QueueFull:
            self.dropped += 1
            self.failure = "journal_queue_overflow_not_complete"

    def record_vosk(self, *, text: str, final: bool, offset_ms: float,
                    sample_cursor: int, frame_seq: int, rms_dbfs: float,
                    turn: int = 0):
        if not text:
            return
        # Capture every CHANGING partial and each final transition, regardless
        # of the UI's separate 150-ms display throttle.
        if final:
            if self.previous_endpoint and text == self.last_final_text:
                return
            self.last_final_text = text
            self.previous_vosk = ""
        elif text == self.previous_vosk and not self.previous_endpoint:
            return
        else:
            self.previous_vosk = text
        self.previous_endpoint = bool(final)
        self.record("vosk_final" if final else "vosk_partial",
                    offset_ms=offset_ms, turn=turn, text=text,
                    engine="vosk-small-ru-0.22",
                    sample_cursor=sample_cursor, frame_seq=frame_seq,
                    rms_dbfs=rms_dbfs, actual=True)

    def _update_summary(self, event):
        turn = event["turn"]
        if turn <= 0:
            return
        t = self.turns.setdefault(
            turn, {"first": {}, "last": {}, "cloud_transcript": None,
                   "question": None, "answer": None,
                   "answer_deltas": [], "cloud_deltas": [],
                   "status": "IN_PROGRESS", "finalized": False})
        stage = event["stage"]
        if stage in SUMMARY_STAGES:
            t["first"].setdefault(stage, event["since_session_ms"])
            t["last"][stage] = event["since_session_ms"]
        if stage == "cloud_partial":
            t["cloud_deltas"].append(event.get("text", ""))
        if stage == "cloud_final":
            t["cloud_transcript"] = event.get("text")
        if stage == "brain_question":
            t["question"] = event.get("question")
        if stage == "brain_delta":
            t["answer_deltas"].append(event.get("text", ""))
        if stage == "brain_final":
            t["answer"] = event.get("text")
        if stage == "cloud_rejected":
            t["status"] = "NOT_CONFIRMED_" + str(event.get("status"))
        if stage == "playback_drained":
            t["status"] = "SPEAKER_DRAINED"
        if stage == "error":
            t["status"] = "ERROR_" + str(event.get("code"))[:65]

    def summarize_turn(self, turn: int, *, outcome: str | None = None):
        t = self.turns.get(turn)
        if not t or t["finalized"]:
            return
        first = t["first"]
        def between(a, b):
            return (round(first[b] - first[a], 1)
                    if a in first and b in first else None)
        spans = {
            "wake_to_cloud_ready_ms": between("wake", "cloud_ready"),
            "wake_to_stt_final_ms": between("wake", "cloud_final"),
            "stt_final_to_brain_ms": between("cloud_final", "brain_start"),
            "stt_final_to_socket_closed_ms": between("cloud_final", "cloud_socket_closed"),
            "socket_closed_to_brain_ms": between("cloud_socket_closed", "brain_start"),
            "brain_to_first_text_ms": between("brain_start", "brain_first_text"),
            "wake_to_first_audio_ms": between("wake", "tts_first_audio"),
            "followup_to_first_audio_ms": between(
                "followup_speech_start", "tts_first_audio"),
            "followup_commit_to_first_audio_ms": between(
                "followup_audio_commit", "tts_first_audio"),
            "first_audio_to_playback_end_ms": between(
                "tts_first_audio", "playback_drained"),
        }
        status = outcome or t["status"]
        alert = []
        if (spans["stt_final_to_brain_ms"] is not None and
                spans["stt_final_to_brain_ms"] > 1000):
            alert.append("cloud_to_brain_handoff_over_1000ms")
        if (spans["wake_to_first_audio_ms"] is not None and
                spans["wake_to_first_audio_ms"] > 3000):
            alert.append("wake_to_first_audio_over_3000ms")
        if status.startswith("NOT_CONFIRMED_"):
            alert.append("cloud_name_not_confirmed")
        # This categorizes observations; it never calls a model or
        # assumes which word the owner actually pronounced.
        cloud_text = t["cloud_transcript"]
        answer = t["answer"] or "".join(t["answer_deltas"])
        event = {
            "stage": "turn_analysis",
            "turn": turn,
            "status": status,
            "question": t["question"],
            "cloud_transcript": cloud_text,
            "answer": answer,
            "latency_ms": spans,
            "findings": alert,
            "summary_kind": "deterministic_metadata_and_recorded_text",
        }
        t["finalized"] = True
        self.record("turn_analysis", offset_ms=max(first.values(), default=0),
                    turn=turn, question=t["question"], text=answer,
                    status=status)
        # Preserve the complete structured analysis (no credentials/audio).
        self._enqueue_raw({
            "schema": SCHEMA, "at_utc": _stamp(),
            "session": self.session, "turn": turn,
            **event,
        })

    def _enqueue_raw(self, data):
        if self.closed:
            return
        try:
            self.queue.put_nowait(data)
        except asyncio.QueueFull:
            self.dropped += 1
            self.failure = "journal_queue_overflow_not_complete"

    @staticmethod
    def _as_line(event):
        return json.dumps(event, ensure_ascii=False,
                          separators=(",", ":")) + "\n"

    def _append_batch(self, batch):
        if self.failure is not None:
            return
        rendered = "".join(self._as_line(ev) for ev in batch)
        size = len(rendered.encode("utf-8"))
        if size + self._disk_bytes > MAX_FILE_BYTES:
            self.failure = "journal_file_size_limit_not_complete"
            return
        with self.path.open("a", encoding="utf-8", newline="\n") as fp:
            fp.write(rendered)
            fp.flush()
        self._disk_bytes += size
        self.persisted += len(batch)

    async def _writer(self):
        while True:
            value = await self.queue.get()
            if value is None:
                self.queue.task_done()
                return
            batch = [value]
            while len(batch) < 128 and not self.queue.empty():
                other = self.queue.get_nowait()
                if other is None:
                    self.queue.task_done()
                    await self._write_batch_async(batch)
                    return
                batch.append(other)
            await self._write_batch_async(batch)

    async def _write_batch_async(self, batch):
        try:
            await asyncio.to_thread(self._append_batch, batch)
        except Exception as exc:
            self.failure = "journal_disk_write_" + type(exc).__name__
        finally:
            for _ in batch:
                self.queue.task_done()

    async def close(self):
        if self.closed:
            return
        for turn in sorted(self.turns):
            self.summarize_turn(turn, outcome=None)
        self._enqueue_raw({
            "schema": SCHEMA, "at_utc": _stamp(),
            "session": self.session, "stage": "session_end",
            "turn": len(self.turns),
            "complete": self.failure is None and self.dropped == 0,
            "dropped_events": self.dropped,
        })
        if self.task is not None:
            await self.queue.put(None)
            await asyncio.wait_for(self.task, timeout=12)
        self.closed = True

    def snapshot(self):
        return {
            "path": str(self.path),
            "mode": self.mode,
            "events_written": self.persisted,
            "pending_events": self.queue.qsize(),
            "dropped_events": self.dropped,
            "complete_so_far": self.failure is None and self.dropped == 0,
            "failure": self.failure,
            "turn_count": len(self.turns),
        }
