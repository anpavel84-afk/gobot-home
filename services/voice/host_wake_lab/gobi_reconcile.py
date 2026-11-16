"""Reclassify previously measured synthetic v1 errors; NEVER repeat inference.

Owner issue #6 comment 6930851891: the historical "А, Гоби" contains the
keyword, so a "Гоби" event on it is *cross-variant confusion*, not a real
false activation on unrelated daily speech. Preserve original v1 JSON; write
a NEW clearly labeled v2 reinterpretation without altering sample counts.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

ACTIVE = ("gobi", "hey_gobi", "globi")
HISTORICAL_EXCLUDED_TARGET = "a_gobi"
REQUIRED_CATALOG_SHA256 = "f347a09dcf1d7a1e9ae3beab94bbc69976ad4c101f7a1a26fcd5a67d6b85995f"

def classify(clip_id: str, candidate: str) -> str:
    if candidate not in ACTIVE:
        raise ValueError("inactive_candidate")
    if clip_id.startswith(candidate + "_"):
        return "target"
    if clip_id.startswith("negative_"):
        return "unrelated_speech"
    if clip_id.startswith(HISTORICAL_EXCLUDED_TARGET + "_"):
        return "historical_address_A_Gobi"
    if any(clip_id.startswith(other + "_") for other in ACTIVE if other != candidate):
        return "other_distinct_address"
    raise ValueError("unknown_clip_group:" + clip_id)


def summarize_run(run: dict) -> dict:
    candidate = run["candidate_id"]
    if candidate not in ACTIVE:
        raise ValueError("archived_variant_excluded_from_current_comparison")
    if run.get("status") == "BLOCKED":
        return {"candidate": candidate, "engine": run["engine"],
                "status": "BLOCKED", "reason": run.get("reason")}
    counts = {}
    for group in ("target", "unrelated_speech", "other_distinct_address",
                  "historical_address_A_Gobi"):
        counts[group] = {"clips": 0, "events": 0, "hits": 0, "clip_ids_with_events": []}
    for clip in run["events"]:
        group = classify(clip["id"], candidate)
        o = counts[group]
        o["clips"] += 1
        found = clip["events"]
        o["events"] += len(found)
        if found:
            o["clip_ids_with_events"].append(clip["id"])
        if group == "target" and any(e["phrase_id"] == candidate for e in found):
            o["hits"] += 1
    return {
        "candidate": candidate, "engine": run["engine"],
        "status": "SYNTHETIC_RECLASSIFIED_NOT_HUMAN_ACCEPTED",
        "target_detected": counts["target"]["hits"],
        "target_trials": counts["target"]["clips"],
        "target_misses": counts["target"]["clips"] - counts["target"]["hits"],
        "unrelated_speech_false_events": counts["unrelated_speech"]["events"],
        "unrelated_speech_negative_clips": counts["unrelated_speech"]["clips"],
        "other_distinct_address_events": counts["other_distinct_address"]["events"],
        "other_distinct_address_clips": counts["other_distinct_address"]["clips"],
        "historical_A_Gobi_variant_events": counts["historical_address_A_Gobi"]["events"],
        "historical_A_Gobi_variant_clips": counts["historical_address_A_Gobi"]["clips"],
        "clip_ids_by_group": {k: v["clip_ids_with_events"] for k,v in counts.items()},
        "cold_start_ms_v1": run.get("cold_start_ms"),
        "cpu_time_s_v1": run.get("cpu_time_s"),
        "peak_process_rss_mb_v1": run.get("peak_observed_rss_mb"),
        "real_background_exposure_s": 0.0,
        "false_wakes_per_hour": None,
        "name_end_to_ack_p50_ms": None,
        "name_end_to_ack_p95_ms": None,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--previous", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    previous = json.loads(args.previous.read_text(encoding="utf-8"))
    if previous.get("catalog_sha256") != REQUIRED_CATALOG_SHA256:
        raise ValueError("historical_catalog_hash_mismatch_do_not_infer")
    original = args.previous.read_bytes()
    active = [
        summarize_run(run) for run in previous["candidate_model_results"]
        if run.get("candidate_id") in ACTIVE
    ]
    report = {
        "schema": "gobot_host_b_old_synthetic_reclassification_v2",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "old_dataset_sha256": previous["catalog_sha256"],
        "original_report_sha256": hashlib.sha256(original).hexdigest(),
        "new_inference_performed": False,
        "original_report_modified": False,
        "same_audio_as_archived_v1": True,
        "primary": "gobi", "reserve": "hey_gobi", "comparison": "globi",
        "historical_A_Gobi_excluded_from_targets": True,
        "contextual_confusion_not_ambient_false_wake": True,
        "no_human_audio_used": True,
        "all_models_activation_approved": False,
        "results": active,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report,ensure_ascii=False,indent=2),
                        encoding="utf-8")
    for x in active:
        print("ARCHIVED_RECLASSIFIED", x["candidate"],x["engine"],
              "TP",x.get("target_detected","NA"),"/",x.get("target_trials","NA"),
              "FP_UNRELATED",x.get("unrelated_speech_false_events","NA"),
              "CROSS_OTHER",x.get("other_distinct_address_events","NA"),
              "ARCHIVED_A_GOBI",x.get("historical_A_Gobi_variant_events","NA"))
    print("NO_NEW_INFERENCE_OR_HUMAN_MIC_RUN",args.out)

if __name__=="__main__":
    main()
