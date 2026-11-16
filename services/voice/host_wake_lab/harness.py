"""Privacy-preserving same-PCM wake benchmark; NEVER claims fixture tests are live.

Run:
  python -m services.voice.host_wake_lab.harness --manifest FILE
      --models-root DIRECTORY --out FILE [--engines t-one vosk zipformer-window]
Inputs must be explicitly marked public / synthetic / owner-consented.
Results contain no raw PCM or ASR transcripts.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import statistics
import time
import wave

from .detect import SAMPLE_RATE, WakeLab
from .engines import REGISTRY, make_backend

FRAME_SAMPLES = 960
MIN_LATENCY_TRIALS = 20
MIN_BACKGROUND_SECONDS_FOR_FPH = 1800


def read_pcm16(wav_path: Path) -> bytes:
    with wave.open(str(wav_path), "rb") as f:
        meta = (f.getnchannels(), f.getsampwidth(), f.getframerate(),
                f.getcomptype())
        if meta != (1, 2, SAMPLE_RATE, "NONE"):
            raise ValueError("fixture_requires_PCM_s16le_mono_16000:" + str(meta))
        return f.readframes(f.getnframes())


def load_manifest(path: Path, allow_consented: bool = False):
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(doc.get("samples"), list) or not doc["samples"]:
        raise ValueError("empty_dataset")
    seen = set()
    clips = []
    for s in doc["samples"]:
        clip_id = s["id"]
        if not isinstance(clip_id, str) or not clip_id or clip_id in seen:
            raise ValueError("duplicate_or_missing_clip_id")
        seen.add(clip_id)
        kind = s["kind"]
        source = s["source"]
        if kind not in {"positive", "negative", "background"}:
            raise ValueError("unrecognized_kind:" + clip_id)
        if source not in {"public", "synthetic", "consented"}:
            raise ValueError("unverified_source:" + clip_id)
        if source == "consented" and not allow_consented:
            raise PermissionError("owner_consent_required_for_fixture:" + clip_id)
        if kind == "positive" and not s.get("expected_phrase"):
            raise ValueError("positive_requires_expected_phrase")
        audio_path = Path(s["path"])
        if not audio_path.is_absolute():
            audio_path = (path.parent / audio_path).resolve()
        pcm = read_pcm16(audio_path)
        if not pcm:
            raise ValueError("empty_pcm:" + clip_id)
        sha = hashlib.sha256(pcm).hexdigest()
        if s.get("pcm_sha256") and s["pcm_sha256"] != sha:
            raise ValueError("dataset_pcm_hash_mismatch:" + clip_id)
        end = s.get("wake_end_sample")
        if end is not None and (type(end) is not int or not 0 <= end <= len(pcm)//2):
            raise ValueError("invalid_wake_end_sample")
        clips.append({
            "id": clip_id, "kind": kind, "source": source,
            "expected_phrase": s.get("expected_phrase"),
            "wake_end_sample": end, "pcm": pcm, "pcm_sha256": sha,
            "duration_samples": len(pcm) // 2,
        })
    records = [{k: v for k, v in c.items() if k != "pcm"} for c in clips]
    digest = hashlib.sha256(
        json.dumps(records, sort_keys=True, ensure_ascii=False,
                   separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return clips, digest


def nearest_ranks(data):
    """Report P50/P95 only with sufficient independent human annotated trials."""
    if len(data) < MIN_LATENCY_TRIALS:
        return {"n": len(data), "p50_ms": None, "p95_ms": None,
                "gate": f"INSUFFICIENT_TRIALS_min_{MIN_LATENCY_TRIALS}"}
    ordered = sorted(data)
    def percentile(p):
        at = (len(ordered) - 1) * p
        left = math.floor(at)
        right = math.ceil(at)
        return round(ordered[left] + (ordered[right] - ordered[left]) *
                     (at - left), 1)
    return {"n": len(data), "p50_ms": percentile(.5),
            "p95_ms": percentile(.95), "gate": "MEASURED_AUDIO_OFFSET_ONLY"}


def benchmark_one(engine_name: str, root: str, clips: list, threads: int = 2):
    import psutil
    process = psutil.Process(os.getpid())
    cold_start = time.perf_counter()
    try:
        decoder = make_backend(engine_name, root, threads=threads)
    except Exception as exc:
        return {
            "engine": engine_name, "status": "BLOCKED",
            "reason": f"{type(exc).__name__}:{exc}",
            "version": REGISTRY[engine_name].model_version,
            "license": REGISTRY[engine_name].license,
            "native_rate": REGISTRY[engine_name].native_rate,
            "native_streaming": REGISTRY[engine_name].streaming,
            "cold_start_ms": None, "events": [],
        }
    cold_ms = (time.perf_counter() - cold_start) * 1000
    model_rss = process.memory_info().rss
    CPU0 = process.cpu_times()
    elapsed0 = time.perf_counter()
    samples_out = []
    max_rss = model_rss
    total_samples = 0
    frame_count = 0
    for clip in clips:
        detector = WakeLab(decoder)
        detector.reset()
        pcm = clip["pcm"]
        # Identical 1.20 seconds of post-clip silence for all decoders.
        extended = pcm + b"\0\0" * int(SAMPLE_RATE * 1.2)
        stream_epoch = "fixture_" + hashlib.sha256(clip["id"].encode("utf-8")).hexdigest()[:24]
        detections = []
        for i in range(0, len(extended), FRAME_SAMPLES * 2):
            frame = extended[i:i + FRAME_SAMPLES * 2]
            first_sample = i // 2
            events = detector.feed(
                pcm_s16le=frame, stream_epoch=stream_epoch,
                sample_index=first_sample,
                received_monotonic_ns=10_000_000_000_000 + int(first_sample * 1_000_000_000 / SAMPLE_RATE),
            )
            frame_count += 1
            for event in events:
                offset = (event["end_sample_index"] -
                          clip["wake_end_sample"]) * 1000 / SAMPLE_RATE if (
                              clip["wake_end_sample"] is not None) else None
                detections.append({
                    "phrase_id": event["phrase_id"],
                    "end_sample_index": event["end_sample_index"],
                    "audio_offset_after_name_ms": (
                        round(offset, 1) if offset is not None else None
                    ),
                })
        samples_out.append({
            "id": clip["id"], "kind": clip["kind"], "source": clip["source"],
            "expected_phrase": clip["expected_phrase"],
            "duration_s": round(clip["duration_samples"] / SAMPLE_RATE, 3),
            "pcm_sha256": clip["pcm_sha256"],
            "events": detections,
        })
        total_samples += clip["duration_samples"]
        max_rss = max(max_rss, process.memory_info().rss)
    wall_s = time.perf_counter() - elapsed0
    CPU1 = process.cpu_times()
    cpu_s = CPU1.user + CPU1.system - CPU0.user - CPU0.system
    positives = [c for c in samples_out if c["kind"] == "positive"]
    negatives = [c for c in samples_out if c["kind"] != "positive"]
    true_positive = sum(
        any(e["phrase_id"] == c["expected_phrase"] for e in c["events"])
        for c in positives
    )
    misses = len(positives) - true_positive
    false_events = sum(len(c["events"]) for c in negatives)
    background_s = sum(c["duration_s"] for c in negatives
                       if c["kind"] == "background" and c["source"] != "synthetic")
    background_false = sum(len(c["events"]) for c in negatives
                           if c["kind"] == "background" and c["source"] != "synthetic")
    annotated_human_offsets = [
        e["audio_offset_after_name_ms"]
        for c in positives if c["source"] != "synthetic"
        for e in c["events"][:1]
        if e["phrase_id"] == c["expected_phrase"]
        and e["audio_offset_after_name_ms"] is not None
    ]
    return {
        "engine": engine_name, "version": decoder.model_version,
        "license": decoder.license, "native_rate": decoder.native_rate,
        "native_streaming": decoder.streaming,
        "status": "FREE_TESTED_NOT_HUMAN_ACCEPTED",
        "positive_trials": len(positives), "true_positive": true_positive,
        "misses": misses, "negative_trials": len(negatives),
        "false_events": false_events,
        "background_exposure_s": round(background_s, 3),
        "false_wakes_per_hour": (round(background_false * 3600 / background_s, 4)
                                 if background_s >= MIN_BACKGROUND_SECONDS_FOR_FPH
                                 else None),
        "latency_audio_offset": nearest_ranks(annotated_human_offsets),
        "cold_start_ms": round(cold_ms, 1),
        "warm_replay_wall_s": round(wall_s, 3),
        "replay_audio_s": round(total_samples / SAMPLE_RATE, 3),
        "realtime_factor": round(wall_s / (total_samples / SAMPLE_RATE), 3),
        "cpu_time_s": round(cpu_s, 3),
        "cpu_cores_equivalent": round(cpu_s / wall_s, 3) if wall_s else None,
        "rss_after_model_mb": round(model_rss / 1048576, 1),
        "peak_observed_rss_mb": round(max_rss / 1048576, 1),
        "replayed_frames": frame_count,
        "events": samples_out,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--models-root", required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--engines", nargs="+", choices=REGISTRY,
                   default=["t-one", "vosk", "zipformer-window"])
    p.add_argument("--threads", type=int, default=2)
    p.add_argument("--allow-consented", action="store_true",
                   help="requires explicit prior Owner permission for the named fixtures")
    args = p.parse_args()
    if not 1 <= args.threads <= 4:
        p.error("thread_count_must_be_1_to_4")
    clips, dataset_hash = load_manifest(args.manifest, args.allow_consented)
    report = {
        "schema": "gobot_host_wake_lab_v1",
        "created_at_utc": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).isoformat(),
        "dataset_hash": dataset_hash,
        "dataset_clips": len(clips),
        "dataset_human_live": False,
        "pcm_format": "s16le mono 16000 Hz",
        "frame_samples": FRAME_SAMPLES,
        "tail_silence_s": 1.2,
        "machine": platform.node(),
        "py_version": platform.python_version(),
        "source_implemented": True,
        "pc_mic_human_accepted": "NOT_RUN_CONSENT_REQUIRED",
        "board_human_accepted": "NOT_RUN_HOST_A_ONLY",
        "paid_session_calls": 0,
        "engine_results": [benchmark_one(e, args.models_root, clips,
                                         threads=args.threads) for e in args.engines],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False),
                        encoding="utf-8")
    for x in report["engine_results"]:
        print(x["engine"], x["status"],
              "TP", x.get("true_positive", "NA"),
              "FP", x.get("false_events", "NA"),
              "cold_ms", x.get("cold_start_ms", "NA"),
              "rtf", x.get("realtime_factor", "NA"),
              "blocker", x.get("reason", "-"))
    print("DATASET_SHA256", dataset_hash, "RESULTS", args.out)


if __name__ == "__main__":
    main()
