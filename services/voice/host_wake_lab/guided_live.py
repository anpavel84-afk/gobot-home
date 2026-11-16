r"""Opt-in bounded HUMAN PC-microphone trial; same ephemeral PCM for two decoders.

Nothing captures unless Owner types YES-PC-MIC at the local PLAN terminal.
Raw PCM is held in memory for the duration of ONE trial only and zeroized.
Never uploads or persists PCM, human transcripts, or private models.
Only an Owner-self-confirmed prompted trial can count as a denominator.
One engine runs LIVE during mic capture; the other performs SHADOW replay of
the same ephemeral PCM after the microphone closes. Its replay is NOT live
latency. This program never starts a Brain or a conversation.

Example:
  python -m services.voice.host_wake_lab.guided_live --owner-consent-live \
     --models-root C:\Users\PLAN\gobot\HOST-B-lab\models --device 21 \
     --engine t-one --shadow-engine zipformer-window
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import queue
import threading
import time
import uuid

from .detect import WakeLab
from .engines import REGISTRY, make_backend

PCM_HZ = 16000
FRAME_SAMPLES = 960

TRIALS = (
    ("gobot", "positive", "gobot", "Гобот"),
    ("gabot", "positive", "gabot", "Габот"),
    ("hey-gobot", "positive", "hey_gobot", "Эй, Гобот"),
    ("hello-gobot", "positive", "privet_gobot", "Привет, Гобот"),
    ("a-gobot", "positive", "a_gobot", "А-Гобот"),
    ("gobot-weather", "positive", "gobot", "Гобот, какая сегодня погода? — БЕЗ ПАУЗЫ"),
    ("gabot-weather", "positive", "gabot", "Габот, какая сегодня погода? — БЕЗ ПАУЗЫ"),
    ("gobot-time", "positive", "gobot", "Гобот, который сейчас час? — БЕЗ ПАУЗЫ"),
    ("robot-weather", "negative", None, "Робот, какая сегодня погода?"),
    ("rabota", "negative", None, "Работа идёт своим чередом"),
    ("vot-weather", "negative", None, "Вот какая сегодня погода"),
    ("hey-robot", "negative", None, "Эй, робот"),
    ("background-chat", "negative", None, "Мы сегодня говорили про робота"),
)


def score_trial(kind: str, expected_phrase: str | None, events: list[dict]):
    """Pure scoring, no transcript logging and no synthetic->human confusion."""
    phrases = [x["phrase_id"] for x in events]
    if kind == "positive":
        if not expected_phrase:
            raise ValueError("positive_requires_ground_truth")
        return {"hit": expected_phrase in phrases,
                "wrong_candidates": sum(p != expected_phrase for p in phrases),
                "false_events": 0}
    if kind in ("negative", "tv_background"):
        if expected_phrase:
            raise ValueError("negative_must_not_have_wake")
        return {"hit": False, "wrong_candidates": 0,
                "false_events": len(phrases)}
    raise ValueError("unknown_trial_kind")


def make_summary(engine: str, backend):
    return {
        "engine": engine, "model": backend.model_version,
        "license": backend.license, "native_rate": backend.native_rate,
        "native_streaming": backend.streaming,
        "positive_trials": 0, "correct_hits": 0, "misses": 0,
        "negative_trials": 0, "false_events": 0,
        "wrong_positive_events": 0,
        "measured_background_seconds": 0,
        "false_wakes_per_hour": None, "name_end_to_ack_p50_ms": None,
        "name_end_to_ack_p95_ms": None,
    }


def process_pcm(backend, pcm: bytearray, epoch: str):
    """Replay after capture; receiver positions correspond to recorded PCM only."""
    decoder = WakeLab(backend)
    decoder.reset()
    events = []
    for i in range(0, len(pcm), FRAME_SAMPLES * 2):
        data = bytes(pcm[i:i + FRAME_SAMPLES * 2])
        events.extend(decoder.feed(
            pcm_s16le=data, stream_epoch=epoch, sample_index=i // 2,
            received_monotonic_ns=1_000_000_000_000 + (i // 2) * 62500,
        ))
    decoder.reset()
    return events


def capture_live(backend, *, device: int, seconds: float):
    """Returns a mutable in-memory PCM buffer and LIVE primary candidates only."""
    import sounddevice as sd
    if not 2 <= seconds <= 8 and seconds != 30:
        raise ValueError("invalid_capture_duration")
    decoder = WakeLab(backend)
    decoder.reset()
    epoch = uuid.uuid4().hex
    frames = queue.Queue(maxsize=12)
    fault = threading.Event()
    pcm = bytearray()
    detected = []
    index = 0
    measured_peak_backlog_ms = 0.0

    def callback(data, nframes, time_info, status):
        if status or nframes != FRAME_SAMPLES:
            fault.set()
            return
        try:
            frames.put_nowait((bytes(data), time.monotonic_ns()))
        except queue.Full:
            fault.set()

    try:
        with sd.RawInputStream(samplerate=PCM_HZ, blocksize=FRAME_SAMPLES,
                              dtype="int16", channels=1, device=device,
                              callback=callback):
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                if fault.is_set():
                    raise RuntimeError("capture_backpressure_fault")
                try:
                    part, recv_ns = frames.get(timeout=.3)
                except queue.Empty:
                    continue
                pcm.extend(part)
                measured_peak_backlog_ms = max(
                    measured_peak_backlog_ms, (time.monotonic_ns() - recv_ns) / 1e6)
                emitted = decoder.feed(
                    pcm_s16le=part, stream_epoch=epoch, sample_index=index,
                    received_monotonic_ns=recv_ns,
                )
                detected.extend(emitted)
                index += len(part) // 2
    except BaseException:
        pcm[:] = bytes(len(pcm))
        pcm.clear()
        raise
    finally:
        decoder.reset()
        while not frames.empty():
            frames.get_nowait()
    return pcm, detected, epoch, round(measured_peak_backlog_ms, 2)


def display_event_summary(events: list[dict]):
    return [(event["phrase_id"], event["end_sample_index"]) for event in events]


def prompt_confirm(input_fn=input, output_fn=print):
    """Do not silently exclude a recorded trial on an accidental Enter.

    Explicit Owner confirmation is mandatory. Recognize RU/EN yes variants.
    Empty or unrecognized input prompts again rather than defaulting yes/no.
    """
    while True:
        reply = input_fn(
            "Подтвердить, что произнесли фразу? y / yes / да = ЗАСЧИТАТЬ; "
            "n / no / нет = НЕ засчитывать: "
        ).strip().casefold()
        if reply in ("y", "yes", "да", "д"):
            return True
        if reply in ("n", "no", "нет", "н"):
            return False
        output_fn(
            "Enter НЕ засчитывает и НЕ пропускает попытку. "
            "Пожалуйста, ответьте y/yes/да или n/no/нет."
        )


def pcm_signal_levels(pcm: bytearray):
    """Non-reversible numeric levels only; NOT human speech verification."""
    import numpy as np
    samples = np.frombuffer(pcm, dtype="<i2").astype(np.float64)
    if not len(samples):
        return {"rms_dbfs": None, "peak_dbfs": None}
    rms = float(np.sqrt(np.mean(samples * samples)))
    peak = float(np.max(np.abs(samples)))
    def dbfs(amplitude):
        return round(20.0 * math.log10(max(amplitude, 1e-8) / 32768.0), 1)
    return {"rms_dbfs": dbfs(rms), "peak_dbfs": dbfs(peak)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner-consent-live", action="store_true")
    parser.add_argument("--models-root", type=Path, required=True)
    parser.add_argument("--device", type=int, default=21)
    parser.add_argument("--engine", choices=REGISTRY, default="t-one")
    parser.add_argument("--shadow-engine", choices=("none", "t-one", "zipformer-window"),
                        default="zipformer-window")
    parser.add_argument("--trial-seconds", type=float, default=4)
    parser.add_argument("--rounds", type=int, default=1)
    parser.add_argument("--only", nargs="+", choices=[t[0] for t in TRIALS],
                        help="Replay only selected prompts; preserves separate new report")
    parser.add_argument("--include-tv-negative", action="store_true")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if not args.owner_consent_live:
        print("NOT_RUN_CONSENT_REQUIRED; microphone unopened")
        return
    if not 2 <= args.trial_seconds <= 8 or args.rounds not in (1, 2, 3):
        parser.error("trial_seconds_2_to_8_and_rounds_1_to_3")
    if args.shadow_engine == args.engine:
        parser.error("shadow_engine_must_differ_from_live_primary")
    selected = [t for t in TRIALS if args.only is None or t[0] in set(args.only)]
    planned_capture = len(selected) * args.rounds * args.trial_seconds
    if args.include_tv_negative:
        planned_capture += 30.0
    if planned_capture > 300:
        parser.error("total_open_mic_time_must_be_300_seconds_or_less")
    print("HOST-B human microphone trial: PLAN only, no recordings/transcripts.")
    print("Each trial: ENTER starts; after speaking you MUST type y/yes/да to COUNT it.")
    print("At confirmation, blank Enter will ask again and NEVER silently exclude.")
    print("Mic opens ONLY for that trial; shared PCM lives only in RAM and is zeroized.")
    print("T-one live vs shadow offline Zipformer are NOT equivalent latency measurements.")
    print("Models are NOT_ACCEPTED. No Brain/B/C/CLI or hardware gateway operations.")
    print("Owner physically at the PLAN Windows console must type YES-PC-MIC.")
    if input("Local consent: ").strip() != "YES-PC-MIC":
        print("NOT_RUN_CONSENT_DENIED")
        return
    import psutil
    proc = psutil.Process(os.getpid())
    model_start = time.perf_counter()
    live = make_backend(args.engine, args.models_root, threads=1)
    live_load_ms = round((time.perf_counter() - model_start) * 1000, 1)
    shadow = None
    shadow_load_ms = None
    if args.shadow_engine != "none":
        model_start = time.perf_counter()
        shadow = make_backend(args.shadow_engine, args.models_root, threads=1)
        shadow_load_ms = round((time.perf_counter() - model_start) * 1000, 1)
    stats = {args.engine: make_summary(args.engine, live)}
    if shadow is not None:
        stats[args.shadow_engine] = make_summary(args.shadow_engine, shadow)
    trials = list(selected) * args.rounds
    if args.include_tv_negative:
        trials.append(("tv-background", "tv_background", None,
                       "Включите ТВ с обычной речью (НЕ произносите обращений)"))
    results = []
    excluded_trials = []
    cpu0 = proc.cpu_times()
    started = time.perf_counter()
    peak_rss = proc.memory_info().rss

    for i, (ident, kind, expected, prompt) in enumerate(trials, 1):
        print(f"\nTRIAL {i}/{len(trials)} ({kind}) · {prompt}")
        answer = input("Enter=start  |  s=skip  |  q=finish: ").strip().lower()
        if answer == "q":
            excluded_trials.append({"trial_id": ident, "reason": "OWNER_FINISHED_EARLY"})
            break
        if answer == "s":
            excluded_trials.append({"trial_id": ident, "reason": "SKIPPED_BEFORE_CAPTURE"})
            print("SKIPPED_NOT_COUNTED", ident)
            continue
        if answer != "":
            excluded_trials.append({"trial_id": ident, "reason": "INVALID_START_INPUT"})
            print("INVALID_SELECTION_SKIP; mic not opened; not counted", ident)
            continue
        seconds = 30.0 if kind == "tv_background" else args.trial_seconds
        print("MIC_OPENING; speak naturally as prompted.")
        pcm = None
        try:
            pcm, live_events, epoch, queue_backlog_ms = capture_live(
                live, device=args.device, seconds=seconds)
            print("MIC_CLOSED", "captured_s", round(len(pcm) / (PCM_HZ*2), 2),
                  "primary_event_count", len(live_events))
            print("Primary candidates", display_event_summary(live_events))
            shadow_events = []
            if shadow is not None:
                shadow_events = process_pcm(shadow, pcm, epoch)
                print("Shadow candidates", display_event_summary(shadow_events))
            levels = pcm_signal_levels(pcm)
            print("MIC_SIGNAL_LEVEL", levels,
                  "levels_only_no_transcripts_or_recording")
            if levels["rms_dbfs"] is not None and levels["rms_dbfs"] < -52:
                print("WARNING_QUIET_MIC: signal may be muted or too weak")
            if not prompt_confirm():
                excluded_trials.append({"trial_id": ident, "reason": "OWNER_DECLINED_AFTER_CAPTURE"})
                print("EXCLUDED_BY_OWNER, not included in denominators", ident)
                continue
            print("TRIAL_COUNTED", ident)
            per_engine = [(args.engine, live_events)]
            if shadow is not None:
                per_engine.append((args.shadow_engine, shadow_events))
            for name, events in per_engine:
                s = stats[name]
                score = score_trial(kind, expected, events)
                if kind == "positive":
                    s["positive_trials"] += 1
                    s["correct_hits"] += int(score["hit"])
                    s["misses"] += int(not score["hit"])
                    s["wrong_positive_events"] += score["wrong_candidates"]
                else:
                    s["negative_trials"] += 1
                    s["false_events"] += score["false_events"]
                    if kind == "tv_background":
                        s["measured_background_seconds"] += round(len(pcm)/(PCM_HZ*2), 2)
            results.append({
                "trial_id": f"{ident}-trial{i}", "kind": kind,
                "expected_phrase": expected, "owner_confirmed": True,
                "duration_seconds": round(len(pcm) / (PCM_HZ * 2), 2),
                "primary_event_phrases": [x["phrase_id"] for x in live_events],
                "shadow_event_phrases": [x["phrase_id"] for x in shadow_events],
                "live_queue_max_backlog_ms": queue_backlog_ms,
                "mic_signal_levels": levels,
            })
            peak_rss = max(peak_rss, proc.memory_info().rss)
        finally:
            if pcm is not None:
                pcm[:] = bytes(len(pcm))
                pcm.clear()
            live.reset()
            if shadow is not None:
                shadow.reset()

    cpu1 = proc.cpu_times()
    used_cpu = cpu1.user + cpu1.system - cpu0.user - cpu0.system
    wall = time.perf_counter() - started
    for s in stats.values():
        # No exact acoustic word-end annotations exist for non-recorded voice.
        s["human_name_end_annotated"] = False
        s["status"] = "SELF_CONFIRMED_HUMAN_TRIALS_NOT_AUTO_ACCEPTED"
        s["false_wakes_per_hour"] = None  # <30min independent TV exposure
    result = {
        "schema": "gobot_host_b_guided_human_v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "PLAN_OWNER_SELF_CONFIRMED_LIVE_PCM_IN_MEMORY_ONLY",
        "primary_live_engine": args.engine,
        "shadow_offline_replay_engine": args.shadow_engine,
        "live_model_load_ms": live_load_ms,
        "shadow_model_load_ms": shadow_load_ms,
        "captured_pcm_persisted": False, "asr_transcripts_persisted": False,
        "audio_transferred": False, "paid_calls": 0,
        "name_end_to_ack_latency_measured": False,
        "p50_p95_status": "NOT_MEASURED_NO_INDEPENDENT_NAME_END_ANNOTATION",
        "tv_exposure_owner_confirmed": any(t["kind"] == "tv_background" for t in results),
        "cpu_time_s": round(used_cpu, 3), "wall_s": round(wall, 3),
        "cpu_cores_equivalent": round(used_cpu/wall, 3) if wall else None,
        "peak_process_rss_mb": round(peak_rss/1048576, 1),
        "engine_results": stats, "trials": results,
        "planned_trial_count": len(trials), "counted_trial_count": len(results),
        "excluded_trials": excluded_trials,
    }
    out = args.out or (args.models_root.parent / "results" /
                       ("guided-human-meta-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".json"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    for engine, s in stats.items():
        print("HUMAN_SELF_CONFIRMED", engine,
              "positive", s["correct_hits"], "/", s["positive_trials"],
              "negative_false_events", s["false_events"],
              "negative_trials", s["negative_trials"])
    print("COUNTED", len(results), "EXCLUDED", len(excluded_trials),
          "PLANNED", len(trials))
    print("METADATA_ONLY_REPORT", out, "PAID_CALLS=0")
    print("NOT_ACCEPTED_UNTIL_OWNER_REVIEWS_HUMAN_RESULTS")


if __name__ == "__main__":
    main()
