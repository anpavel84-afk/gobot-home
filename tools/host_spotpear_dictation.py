"""Owner-consented, temporary Spotpear microphone dictation over the existing
HOST-A Opus/WSS transport. No PC mic, network ASR, audio recording or
persistent transcripts. Uses the one existing A-owned COM3/listener pipeline.

The detector output is intentionally SHADOW ONLY: no wake events are emitted.
"""
from __future__ import annotations

import argparse
import array
import asyncio
import json
import math
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import host_monika_live as pilot


class SpotpearDictationDetector:
    """Wraps existing A/B Vosk, prints changing hypotheses and level aggregates."""

    def __init__(self, delegate):
        self.delegate = delegate
        self.delegate.suppress_events = True
        self.suppress_events = True
        self.last_text = ""
        self.last_partial_at = 0.0
        self.window_started = time.monotonic()
        self.window_frames = 0
        self.window_samples = 0
        self.window_energy = 0
        self.window_peak = 0
        self.window_clip = 0
        self.window_nonquiet = 0
        self.total_frames = 0
        self.total_hypotheses = 0
        self.total_finals = 0
        self.previous_end = None
        self.previous_epoch = None

    @property
    def frames(self):
        return self.delegate.frames

    @property
    def events(self):
        return 0

    def reset(self):
        self.delegate.reset()
        self.delegate.suppress_events = True
        self.last_text = ""
        self.last_partial_at = 0.0
        self.previous_end = None
        self.previous_epoch = None
        print("[TRANSPORT] Decoder reset / next authenticated device connection", flush=True)

    @staticmethod
    def dbfs(value):
        return "-inf" if value <= 0 else f"{20.0 * math.log10(value / 32768):.1f}"

    def feed_chunk(self, chunk):
        if self.previous_epoch == chunk.stream_epoch and self.previous_end is not None:
            if self.previous_end != chunk.sample_index:
                print("[TRANSPORT] PCM sample discontinuity observed", flush=True)
        self.previous_epoch = chunk.stream_epoch
        samples = array.array("h")
        samples.frombytes(chunk.pcm_s16le)
        if sys.byteorder != "little":
            samples.byteswap()
        self.previous_end = chunk.sample_index + len(samples)
        self.window_frames += 1
        self.total_frames += 1
        self.window_samples += len(samples)
        self.window_energy += sum(int(x) * int(x) for x in samples)
        peak = max((abs(x) for x in samples), default=0)
        self.window_peak = max(self.window_peak, peak)
        self.window_clip += sum(abs(x) >= 32700 for x in samples)
        frame_rms = math.sqrt(sum(int(x) * int(x) for x in samples) / max(len(samples), 1))
        self.window_nonquiet += (frame_rms >= 100.0)

        # The existing B detector is fed the exact A-decoded 16-kHz PCM.
        # Suppressing events guarantees that ordinary dictation never starts a
        # conversation, local reply or paid session.
        self.delegate.suppress_events = True
        self.delegate.feed_chunk(chunk)
        hypothesis = self.delegate.inner.lab.last_hypothesis
        now = time.monotonic()
        if hypothesis is not None:
            text = str(hypothesis.text).strip()
            if text and text != self.last_text and (
                hypothesis.endpoint or now - self.last_partial_at >= 0.30
            ):
                kind = "FINAL" if hypothesis.endpoint else "PARTIAL"
                print(f"[VOSK {kind}] {text}", flush=True)
                self.total_hypotheses += 1
                self.last_partial_at = now
                self.last_text = text
            if hypothesis.endpoint:
                self.total_finals += 1
                self.last_text = ""

        if now - self.window_started >= 3.0:
            rms = math.sqrt(self.window_energy / max(self.window_samples, 1))
            print(
                "[SIGNAL Spotpear] "
                f"frames={self.window_frames} samples={self.window_samples} "
                f"rms={self.dbfs(rms)}dBFS peak={self.dbfs(self.window_peak)}dBFS "
                f"clipped={self.window_clip} nonquiet={self.window_nonquiet}/{self.window_frames} "
                f"total_frames={self.total_frames} total_finals={self.total_finals}",
                flush=True,
            )
            self.window_started = now
            self.window_frames = 0
            self.window_samples = 0
            self.window_energy = 0
            self.window_peak = 0
            self.window_clip = 0
            self.window_nonquiet = 0
        return None


def main():
    parser = argparse.ArgumentParser(description="Real Spotpear -> PLAN free Vosk dictation")
    parser.add_argument("--owner-approved-mic", action="store_true")
    parser.add_argument("--seconds", type=int, default=600)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    if not args.owner_approved_mic:
        parser.error("Local owner consent required: --owner-approved-mic")
    if not 60 <= args.seconds <= 900:
        parser.error("Dictation duration must be 60..900 seconds")

    original_factory = pilot.make_owner_authorized_factory
    original_gateway = pilot.Gateway

    class ObservedGateway(original_gateway):
        async def handle(self, ws):
            started = time.monotonic()
            try:
                return await super().handle(ws)
            finally:
                h = self.stats.get("host") or {}
                print(json.dumps({
                    "event": "SPOTPEAR_CONNECTION_END",
                    "duration_s": round(time.monotonic() - started, 2),
                    "packets": h.get("received_packets"),
                    "failure_code": h.get("last_failure_code"),
                    "failure_kind": h.get("last_failure_kind"),
                    "queue_max_ms": h.get("max_queue_age_ms"),
                    "queue_max_frames": h.get("max_queue_frames"),
                    "abrupt_close": h.get("abrupt_device_close"),
                    "paid_calls": 0,
                }, ensure_ascii=False), flush=True)

    # This affects only future launches of this temporary diagnostic script.
    # The currently running pilot and its production parent files are untouched.
    pilot.Gateway = ObservedGateway

    def patched_factory(*a, **kw):
        existing_factory = original_factory(*a, **kw)
        return lambda: SpotpearDictationDetector(existing_factory())

    pilot.make_owner_authorized_factory = patched_factory
    print(
        "SPOTPEAR LIVE DICTATION | Vosk on decoded physical 16kHz PCM. "
        "No PC microphone. No audio/transcript storage, no paid calls, no wake actions. "
        "Screen may show HOST Ready; only text console is the diagnostic.",
        flush=True,
    )
    asyncio.run(
        pilot.main(
            SimpleNamespace(
                owner_direct_monika=True,
                seconds=args.seconds,
                preflight_only=args.preflight_only,
            )
        )
    )


if __name__ == "__main__":
    main()
