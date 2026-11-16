r"""Consent-gated PC microphone live wake+local command demo.

Default command lists no audio. This script NEVER saves microphone PCM or
ASR transcript and NEVER starts a cloud session. Requires typed LOCAL consent.

python -m services.voice.host_wake_lab.live --list-mics
python -m services.voice.host_wake_lab.live --engine t-one \
  --models-root C:\...\HOST-B-lab\models --device 21 --seconds 90 \
  --owner-consent-live --piper-model C:\...\ru_RU-denis-medium.onnx
"""
from __future__ import annotations
import argparse
import queue
import sys
import threading
import time
import uuid

from .detect import WakeLab
from .engines import REGISTRY, make_backend
from .local_command import (
    OfflineSpeaker, beep_ack, parse_local_intent, time_answer, timer_answer,
)


def list_microphones():
    import sounddevice as sd
    print("No capture opened. Available PLAN input devices:")
    for i, item in enumerate(sd.query_devices()):
        if item["max_input_channels"]:
            print(i, repr(item["name"]),
                  "max_inputs", item["max_input_channels"],
                  "default_Hz", item["default_samplerate"])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--list-mics", action="store_true")
    p.add_argument("--engine", choices=REGISTRY, default="t-one")
    p.add_argument("--models-root")
    p.add_argument("--device", type=int)
    p.add_argument("--seconds", type=int, default=90)
    p.add_argument("--owner-consent-live", action="store_true")
    p.add_argument("--piper-model", help="read-only existing local Russian voice model")
    args = p.parse_args()
    if args.list_mics:
        list_microphones()
        return
    if args.seconds < 10 or args.seconds > 300:
        p.error("bounded_live_demo_requires_10_to_300_seconds")
    if not args.models_root:
        p.error("--models-root required for actual live decode")
    if not args.owner_consent_live:
        print("NOT_RUN_CONSENT_REQUIRED. Audio capture was not opened.")
        return
    print("This opens the PLAN microphone for", args.seconds, "seconds.")
    print("No PCM or ASR transcripts saved. No streaming to internet.")
    print("The device speaker may play an ACK and a LOCAL time response.")
    print("Owner physically at PLAN must type exactly: YES-PC-MIC")
    if input("Local Owner consent: ").strip() != "YES-PC-MIC":
        print("NOT_RUN_CONSENT_NOT_GRANTED")
        return
    import sounddevice as sd
    backend = make_backend(args.engine, args.models_root, threads=1)
    speaker = OfflineSpeaker(args.piper_model) if args.piper_model else None
    decoder = WakeLab(backend)
    epoch = uuid.uuid4().hex
    frames: queue.Queue[tuple[bytes, float]] = queue.Queue(maxsize=16)
    overflow = threading.Event()
    playing = threading.Event()
    speaker_thread = None
    awaiting_intent_until = 0.
    sequence_samples = 0
    wake_events = 0
    local_actions = 0
    start = time.monotonic()

    def callback(indata, nframes, time_info, status):
        # PortAudio callback is real-time: never decode, print, or send network here.
        if status or nframes != 960:
            overflow.set()
            return
        try:
            frames.put_nowait((bytes(indata), time.monotonic()))
        except queue.Full:
            overflow.set()

    def speak(sentence):
        if not speaker:
            print("LOCAL_COMMAND_TEXT:", sentence)
            beep_ack()
            return
        def task():
            playing.set()
            try:
                speaker.speak(sentence)
            except Exception as exc:
                print("LOCAL_AUDIO_UNAVAILABLE:", type(exc).__name__)
            finally:
                playing.clear()
        nonlocal speaker_thread
        speaker_thread = threading.Thread(target=task, daemon=True)
        speaker_thread.start()

    def run_timer(seconds: int):
        def alarm():
            try:
                beep_ack()
            except Exception:
                pass
        timer = threading.Timer(seconds, alarm)
        timer.daemon = True
        timer.start()

    try:
        with sd.RawInputStream(
            samplerate=16000, blocksize=960, device=args.device,
            channels=1, dtype="int16", callback=callback,
        ):
            print("LIVE_CAPTURE_STARTED epoch", epoch[:8],
                  "engine", decoder.detector_id, "seconds", args.seconds)
            while time.monotonic() - start < args.seconds:
                if overflow.is_set():
                    raise RuntimeError("mic_callback_overflow_or_input_fault")
                try:
                    pcm, received = frames.get(timeout=0.25)
                except queue.Empty:
                    continue
                events = decoder.feed(
                    pcm_s16le=pcm, stream_epoch=epoch,
                    sample_index=sequence_samples,
                    receive_monotonic=received, speaking=playing.is_set(),
                )
                sequence_samples += len(pcm) // 2
                if events:
                    wake_events += len(events)
                    awaiting_intent_until = time.monotonic() + 8
                    print("WAKE_EVENT", events[0]["phrase_id"],
                          "sample", events[0]["end_sample_index"],
                          "detected_monotonic", round(events[0]["detected_monotonic"], 4))
                    beep_ack()
                if awaiting_intent_until and not playing.is_set():
                    intent = parse_local_intent(decoder.last_text)
                    if intent is not None:
                        awaiting_intent_until = 0
                        local_actions += 1
                        if intent.kind == "time":
                            speak(time_answer())
                        else:
                            run_timer(intent.seconds)
                            speak(timer_answer(intent.seconds))
                    elif time.monotonic() > awaiting_intent_until:
                        print("NO_LOCAL_INTENT: conversation remains PAID_BLOCKED")
                        awaiting_intent_until = 0
    finally:
        decoder.reset()
    if speaker_thread:
        speaker_thread.join(timeout=4)
    print("LIVE_CAPTURE_ENDED", "wake_events", wake_events,
          "local_actions", local_actions,
          "audio_written", False, "paid_calls", 0,
          "human_latency_p50_p95", "NOT_ANNOTATED")


if __name__ == "__main__":
    main()
