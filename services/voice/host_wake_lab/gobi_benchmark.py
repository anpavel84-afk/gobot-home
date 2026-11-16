"""Four INDEPENDENT candidate exact-match benchmarks on the SAME public/synthetic PCM.

No live microphone, no training or paid API. Output is metadata + sample hashes,
not audio/transcripts. All variants run as isolated tests, never simultaneously
enabled as production aliases. Report 0/6, false events, latency NOT_MEASURED.
"""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import platform
import sys
from .gobi_policy import CANDIDATES, CANDIDATE_DISPLAY
from .harness import benchmark_one,load_manifest
from .engines import REGISTRY


def main():
    a=argparse.ArgumentParser(description=__doc__)
    a.add_argument("--fixtures-dir",type=Path,required=True)
    a.add_argument("--models-root",type=Path,required=True)
    a.add_argument("--out",type=Path,required=True)
    a.add_argument("--candidates",nargs="+",choices=CANDIDATES,
                   default=["gobi","globi","a_gobi","hey_gobi"])
    a.add_argument("--engines",nargs="+",choices=REGISTRY,
                   default=["t-one","vosk","zipformer-window"])
    a.add_argument("--threads",type=int,default=1)
    args=a.parse_args()
    if args.threads!=1:
        a.error("sequential single CPU thread for reproducible baseline")
    reports=[]
    pcm_hashes=None
    for candidate in args.candidates:
        clips,digest=load_manifest(args.fixtures_dir / f"manifest_{candidate}.json")
        hashes={s["id"]:s["pcm_sha256"] for s in clips}
        if pcm_hashes is not None and hashes!=pcm_hashes:
            raise ValueError("unequal_pcm_across_candidates")
        pcm_hashes=hashes
        for engine in args.engines:
            print("BENCH_START",candidate,engine,flush=True)
            r=benchmark_one(engine,str(args.models_root),clips,threads=args.threads,
                            candidate_id=candidate)
            r["candidate_id"]=candidate
            r["candidate_spelling"]=CANDIDATE_DISPLAY[candidate]
            r["fixture_dataset_sha256"]=digest
            if r["status"]=="BLOCKED":
                print("BENCH_BLOCKED",candidate,engine,r.get("reason"),flush=True)
            else:
                print("BENCH_RESULT",candidate,engine,
                      "TP",r["true_positive"],"/",r["positive_trials"],
                      "FP",r["false_events"],"/",r["negative_trials"],
                      "CPU_s",r["cpu_time_s"],"RSS_MB",r["peak_observed_rss_mb"],
                      "RTF",r["realtime_factor"],flush=True)
            reports.append(r)
    catalog=args.fixtures_dir/"corpus_catalog.json"
    report={
        "schema":"gobot_host_b_gobi_independent_benchmark_v1",
        "timestamp_utc":datetime.now(timezone.utc).isoformat(),
        "candidate_priority":["gobi","globi","a_gobi","hey_gobi"],
        "project_name_unchanged":"GoBot",
        "single_candidate_per_detector":True,
        "all_audio_source":"synthetic_Piper_ru_RU_denis_medium",
        "human_voice_acceptance":"NOT_RUN",
        "real_tv_music_background":"NOT_RUN",
        "false_wakes_per_hour":"NOT_MEASURED",
        "name_end_to_wake_p50_p95":"NOT_MEASURED",
        "actual_mic_distance":"NOT_RUN",
        "activation_approved":False,
        "paid_calls":0,
        "audio_persisted_by_benchmark":False,
        "runtime_python":platform.python_version(),
        "machine":platform.node(),
        "candidate_model_results":reports,
        "common_pcm_hashes_sha256":hashlib.sha256(
            json.dumps(pcm_hashes,sort_keys=True).encode("utf-8")).hexdigest(),
        "catalog_sha256":hashlib.sha256(catalog.read_bytes()).hexdigest(),
    }
    args.out.parent.mkdir(exist_ok=True,parents=True)
    args.out.write_text(json.dumps(report,ensure_ascii=False,indent=2),
                        encoding="utf-8")
    print("BENCH_COMPLETE",len(reports),"pairs","JSON",args.out,
          "COMMON_PCM_SHA256",report["common_pcm_hashes_sha256"],flush=True)


if __name__=="__main__":
    main()
