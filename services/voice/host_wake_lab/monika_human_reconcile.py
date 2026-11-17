"""Re-score a completed Owner-confirmed Monika mic metadata report.

The original report schema v1 used the *display label* "Моника" instead of
machine phrase_id "monika" as expected, incorrectly marking every event a miss.
This tool does NO audio processing, fetches no transcripts and NEVER overwrites
the original JSON. It trusts only count fields emitted by the SINGLE-candidate
Monika detector in each confirmed trial, with primary wake event IDs additionally
cross-checked against cue API request events. A SHADOW event count can mean only
the selected candidate because process_pcm uses CandidateMatcher("monika").
"""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path

EXPECTED_CANDIDATE="monika"
MIN_BACKGROUND_SECONDS=1800


def correct_metadata(raw: dict) -> dict:
    if (raw.get("schema")!="gobot_host_b_gobi_live_v1"
        or raw.get("candidate")!=EXPECTED_CANDIDATE
        or raw.get("spelling")!="Моника"
        or raw.get("one_candidate_only") is not True
        or raw.get("primary_engine_live")!="vosk"
        or raw.get("shadow_engine_postcapture")!="t-one"
        or raw.get("audio_saved") is not False
        or raw.get("trace_hypothesis_text_persisted") is not False
        or raw.get("paid_calls")!=0):
        raise ValueError("unsupported_or_unsafe_input")
    trials=raw.get("trials")
    if not isinstance(trials,list) or not trials:
        raise ValueError("no_trials")
    if raw.get("excluded") or raw.get("capture_errors"):
        raise ValueError("report_contains_excluded_or_faulty_trials")
    seen=set()
    positives=[]
    negatives=[]
    for t in trials:
        if t.get("owner_confirmed") is not True:
            raise ValueError("unconfirmed_trial")
        if not isinstance(t.get("id"),str) or t["id"] in seen:
            raise ValueError("duplicate_or_invalid_trial_id")
        seen.add(t["id"])
        if t["kind"] not in ("positive","negative"):
            raise ValueError("unsupported_kind")
        if t["kind"]=="positive" and not t["id"].startswith("monika-"):
            raise ValueError("positive_trial_other_candidate")
        for key in ("primary_event_count","shadow_event_count"):
            count=t.get(key)
            if type(count) is not int or count < 0 or count > 1:
                raise ValueError("invalid_event_count")
        if t["kind"]=="positive":
            positives.append(t)
        else:
            negatives.append(t)
    primary_positive=sum(int(t["primary_event_count"]>0) for t in positives)
    shadow_positive=sum(int(t["shadow_event_count"]>0) for t in positives)
    primary_negative=sum(t["primary_event_count"] for t in negatives)
    shadow_negative=sum(t["shadow_event_count"] for t in negatives)
    cue=raw.get("cue_api_proxies",[])
    if not isinstance(cue,list) or len(cue)!=sum(t["primary_event_count"] for t in trials):
        raise ValueError("primary_event_cue_count_mismatch")
    if any(item.get("phrase_id")!=EXPECTED_CANDIDATE for item in cue):
        raise ValueError("cue_phrase_not_monika")
    observed_background_seconds=sum(
        t["capture_duration_s"] for t in negatives
        if t.get("condition") in ("conversation","TV_background","music_background")
    )
    if abs(observed_background_seconds-raw.get("actual_background_exposure_s",0))>.11:
        raise ValueError("background_exposure_mismatch")
    def model(name, hits, fp):
        return {
            "model":name,
            "positive_attempts":len(positives),
            "wake_events_detected":hits,
            "misses":len(positives)-hits,
            "negative_attempts":len(negatives),
            "false_events":fp,
            "true_ambient_seconds":round(observed_background_seconds,2),
            "false_wakes_per_hour": (
                round(fp*3600/observed_background_seconds,3)
                if observed_background_seconds >= MIN_BACKGROUND_SECONDS else None
            ),
            "real_name_end_to_wake_p50_ms":None,
            "real_name_end_to_wake_p95_ms":None,
        }
    return {
        "schema":"gobot_host_b_monika_corrected_human_metadata_v2",
        "candidate":"monika",
        "human_mic_source":"PLAN_MME_number_1",
        "primary_live_engine":"vosk",
        "shadow_same_human_pcm_engine":"t-one",
        "source_has_one_candidate_only":True,
        "scoring_bug":"prior_source_compared_phrase_id_monika_to_display_Моника",
        "original_report_preserved":True,
        "no_asr_transcript_persisted":True,
        "paid_calls":0,
        "raw_audio_processed":False,
        "activation_approved":False,
        "source_user_confirmed_trials":len(trials),
        "models":{
            "vosk":model("vosk",primary_positive,primary_negative),
            "t-one":model("t-one",shadow_positive,shadow_negative),
        },
        "per_positive":[
            {"trial_id":t["id"],"Vosk_live":bool(t["primary_event_count"]),
             "T_one_shadow":bool(t["shadow_event_count"]),
             "mic_peak_dbfs":t.get("mic_peak_dbfs")}
            for t in positives
        ],
        "cue_api_requests":len(cue),
        "cue_audible_onset_verified":False,
        "classification":"HUMAN_LAB_EVENTS_OBSERVED_NOT_PRODUCTION_ACCEPTED",
    }


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--in-report",type=Path,required=True)
    p.add_argument("--out-report",type=Path,required=True)
    args=p.parse_args()
    if args.in_report.resolve()==args.out_report.resolve():
        p.error("never_overwrite_original")
    source=args.in_report.read_bytes()
    doc=json.loads(source.decode("utf8"))
    revised=correct_metadata(doc)
    revised["source_report_sha256"]=hashlib.sha256(source).hexdigest()
    revised["created_at_utc"]=datetime.now(timezone.utc).isoformat()
    if args.out_report.exists():
        p.error("corrected_report_already_exists")
    args.out_report.parent.mkdir(exist_ok=True,parents=True)
    args.out_report.write_text(json.dumps(revised,indent=2,ensure_ascii=False),
                               encoding="utf8")
    print("MONIKA_CORRECTED_METADATA_ONLY",args.out_report)
    for key,model in revised["models"].items():
        print(key,"DETECTED",model["wake_events_detected"],"/",
              model["positive_attempts"],"FALSE",model["false_events"],"/",
              model["negative_attempts"],"REAL_BG",model["true_ambient_seconds"],
              "FP_PER_H",model["false_wakes_per_hour"])


if __name__=="__main__":
    main()
