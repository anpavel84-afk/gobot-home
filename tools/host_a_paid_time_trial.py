"""OWNER-approved 3-minute HOST-A physical cloud STT trial.

Existing Spotpear device mic -> A authenticated WSS -> B-vetted Vosk Monika
-> local WakeEvent -> at the end of bounded turn, GPT-Live-Transcribe (paid)
-> strict cloud name confirmation -> deterministic local time + Piper/Opus.

This is an intentionally file-FIRST baseline to diagnose E2E, NOT the final
streaming-first architecture. No audio/transcripts on disk, no other Brain
or paid assistant calls. Financial ledger is strict and persistent.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import deque
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT.parent / "GoBotHome"
sys.path.insert(0, str(ROOT / "services" / "voice"))
sys.path.insert(0, str(MAIN))
import host_monika_live as pilot

from host_a_wake_adapter import WakeGate, DetectorAdapter
from host_a_paid_budget import HostPaidTrialBudget
from host_a_cloud_transcribe import CloudTranscriber
from host_wake_contract import AudioChunk, WakeEvent
from host_local_command import classify_command
from host_a_natural_time_voice import OpenAITimeVoice
from services.brain.gobot.secrets_store import load_openai_key


class GatedCloudTimeResponder:
    def __init__(self, asr_path, voice_path, gate, budget):
        self.voice_path = Path(voice_path)
        self.gate = gate
        self.budget = budget
        # Voice must have been pre-rendered by a separate finite, budgeted
        # owner-approved command. Do not invoke cloud TTS or Piper on a wake.
        self.time_cache = OpenAITimeVoice(
            ROOT / "run" / "host-a" / "natural-time-voice",
            budget, key_loader=load_openai_key)

    def __call__(self, captured_pcm):
        item = self.gate.take()
        if item is None:
            print("HOST_A_NO_LOCAL_WAKE_NO_PAID_SESSION", flush=True)
            return None
        event, prefix_start, replay = item
        # HostCore trims its RAM history at sample granularity. Our A-side
        # observer stores whole 960-sample frames, so the Core capture can
        # begin up to one frame earlier. Match the reviewed whole-frame pre-roll
        # at an even byte offset within that first frame; never guess speech.
        match_at = (captured_pcm.find(replay[:1920], 0, 1920 * 2)
                    if isinstance(captured_pcm, bytes) and replay else -1)
        replay_end = match_at + len(replay)
        if (match_at < 0 or match_at % 2 or
                len(captured_pcm) < replay_end or
                captured_pcm[match_at:replay_end] != replay):
            print("HOST_A_WAKE_AUDIO_MISMATCH_FAIL_CLOSED", flush=True)
            return None
        tail = captured_pcm[replay_end:]
        print("HOST_A_CLOUD_STT_START_AFTER_LOCAL_WAKE", flush=True)

        async def remaining_frames():
            sample = event.end_sample_index
            for offset in range(0, len(tail), 1920):
                part = tail[offset:offset + 1920]
                if not part or len(part) % 4:  # even source sample count
                    raise RuntimeError("tail_pcm_invalid")
                yield AudioChunk(part, event.stream_epoch, sample, 1)
                sample += len(part) // 2

        client = CloudTranscriber(
            self.budget, key_loader=load_openai_key
        )
        try:
            result = asyncio.run(client.transcribe(
                candidate=event, epoch=event.stream_epoch,
                replay_start=prefix_start, replay_pcm16=replay,
                next_frames=remaining_frames(), max_session_seconds=30
            ))
            print("HOST_A_CLOUD_VERDICT=" + result.verdict +
                  " STT_AUDIO_SECONDS=" + str(result.audio_seconds) +
                  " STT_FINAL_MS=" + str(result.final_ms), flush=True)
            if result.verdict != "CONFIRMED":
                return None
            if classify_command(result.question or "") != "local_time":
                print("HOST_A_CLOUD_CONFIRMED_NONLOCAL_QUESTION_NOT_ADMITTED", flush=True)
                return None
            packets, cached = self.time_cache.get()
            if not cached:
                print("HOST_A_NATURAL_VOICE_MISSING_NO_PIPER_NO_PAID_TTS", flush=True)
                return None
            print("HOST_A_NATURAL_OPENAI_TIME_FROM_LOCAL_CACHE", flush=True)
            return packets
        except Exception as error:
            # No traceback/key/audio/private utterance to disk.
            print("HOST_A_CLOUD_FAULT=" + type(error).__name__, flush=True)
            return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--owner-cloud-grant-50m", action="store_true")
    parser.add_argument("--seconds", type=int, default=180)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    if not args.owner_cloud_grant_50m:
        parser.error("OWNER_CLOUD_FINANCIAL_GRANT_REQUIRED")
    if not 60 <= args.seconds <= 180:
        parser.error("HARD_TRIAL_LIMIT_180S")
    budget = HostPaidTrialBudget(
        ROOT / "run" / "host-a" / "paid-trial-20261116"
    )
    # Inspect ledger safely without changing it.
    status = budget.status()
    print("HOST_A_OWNER_BUDGET_CAP_SECONDS=" + str(status["max_seconds"]) +
          " PREVIOUS_RESERVED_SECONDS=" + str(status["reserved_seconds"]) +
          " USD_CAP=" + str(status["max_estimated_usd"]), flush=True)
    gate = WakeGate()
    original_factory = pilot.make_owner_authorized_factory
    original_responder = pilot.OfflineTimeResponder
    original_gateway = pilot.Gateway
    import host_stream
    original_connection = host_stream.HostConnection

    class TracedHostConnection(original_connection):
        async def compute(self, fn, *a, **kw):
            try:
                return await super().compute(fn, *a, **kw)
            except Exception as exc:
                stage = getattr(fn, "__qualname__", type(fn).__name__)
                raw = str(exc)
                code = (raw if raw and len(raw) <= 80 and
                        all(c.isascii() and (c.isalnum() or c in "_.-") for c in raw)
                        else "unclassified")
                print("HOST_A_COMPUTE_FAULT_STAGE=" + stage +
                      " TYPE=" + type(exc).__name__ + " CODE=" + code,
                      flush=True)
                raise

    class ObservedGateway(original_gateway):
        async def handle(self, ws):
            try:
                return await super().handle(ws)
            finally:
                h = self.stats.get("host") or {}
                print("HOST_A_CONNECTION_END kind=" +
                      str(h.get("last_failure_kind")) + " code=" +
                      str(h.get("last_failure_code")) + " packets=" +
                      str(h.get("received_packets")) + " queue_age_max_ms=" +
                      str(round(h.get("max_queue_age_ms", 0) or 0, 2)),
                      flush=True)

    # Only the isolated HOST-A test process, never the production gateway.
    host_stream.HostConnection = TracedHostConnection
    pilot.Gateway = ObservedGateway

    def instrumented_factory(*a, **kw):
        mk = original_factory(*a, **kw)
        return lambda: DetectorAdapter(mk(), gate)

    class CloudResponder:
        def __new__(cls, asr_path, voice_path):
            return GatedCloudTimeResponder(asr_path, voice_path, gate, budget)

    pilot.make_owner_authorized_factory = instrumented_factory
    pilot.OfflineTimeResponder = CloudResponder
    try:
        if args.preflight_only:
            print("HOST_A_CLOUD_PREFLIGHT_ONLY_NO_NETWORK_NO_AUDIO", flush=True)
        asyncio.run(pilot.main(SimpleNamespace(
            owner_direct_monika=True, seconds=args.seconds,
            preflight_only=args.preflight_only,
        )))
    finally:
        host_stream.HostConnection = original_connection
        pilot.Gateway = original_gateway
        pilot.make_owner_authorized_factory = original_factory
        pilot.OfflineTimeResponder = original_responder


if __name__ == "__main__":
    main()
