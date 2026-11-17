"""V3 threshold calibration on ONE validation speaker and two test profiles.

Never tune V3 threshold using its test data. Excludes exact-text overlap
with training/validation from the separate test denominators. Test speaker
Aleksandr-hq is new licensed RHVoice profile, but shares a synthesizer
family with Aleksandr validation; independence is not a human trial.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
from evaluate_heldout import evaluation, score

VAL="aleksandr"
TEST=("elena","aleksandr-hq")
TRAIN=("denis","dmitri","anna","irina","espeak-ru")
THRESHOLDS=(178,191,204,216,229,235,242,248,251,252,253,254,255)

def known_texts(root:Path,speakers):
    texts=set()
    for speaker in speakers:
        for label in ("positive","negative"):
            entries=json.loads((root/speaker/f"manifest-{label}.json").read_text(encoding="utf8"))
            for row in entries:
                texts.add(row["text"].casefold().strip())
    return texts

def heldout_clean(model,corpus,speaker,seen_text):
    all_runs=evaluation(model,corpus,speaker)
    ids={}
    for label in ("positive","negative"):
        for row in json.loads((corpus/speaker/f"manifest-{label}.json").read_text(encoding="utf8")):
            ids[row["file"]]=row["text"].casefold().strip()
    excluded=sorted(r["name_for_error_only"] for r in all_runs
                    if ids[r["name_for_error_only"]] in seen_text)
    clean=[r for r in all_runs if ids[r["name_for_error_only"]] not in seen_text]
    if not clean or len(clean)<80:raise ValueError("insufficient_disjoint_test_clips")
    return clean,excluded

def main(model,corpus,out):
    if out.exists():raise ValueError("no_overwrite_a_previous_test")
    if model.name!="monika_int8.tflite":raise ValueError("unrecognized_target")
    model_digest=hashlib.sha256(model.read_bytes()).hexdigest()
    out.mkdir(parents=True)
    validation=evaluation(model,corpus,VAL)
    sweep={str(t):score(validation,t) for t in THRESHOLDS}
    # A strict heuristic for synthetic-only experimental candidate:
    # at least 75% validation positives and ZERO synthetic validation FPs.
    eligible=[t for t in THRESHOLDS if
              sweep[str(t)]["detected"]>=.75*sweep[str(t)]["positive"]
              and sweep[str(t)]["false_events"]==0]
    if eligible:
        selected=min(eligible)
        verdict="SYNTHETIC_VALIDATION_PASS_ONLY"
    else:
        selected=min(THRESHOLDS,key=lambda t:(
            sweep[str(t)]["false_events"],
            -sweep[str(t)]["detected"],t))
        verdict="SYNTHETIC_VALIDATION_REJECTED"
    val_report={
        "speaker":VAL,"never_trained_on_validation":True,
        "selected_cutoff_before_any_test_eval":selected,
        "smoothing_window":5,"gate":verdict,"sweep":sweep,
    }
    (out/"calibration.json").write_text(json.dumps(val_report,ensure_ascii=False,indent=2))
    print("V3_THRESHOLD_LOCKED_BEFORE_NEW_TEST",selected,verdict,flush=True)
    source_text=known_texts(corpus,(*TRAIN,VAL))
    result={}
    for speaker in TEST:
        clean,excluded=heldout_clean(model,corpus,speaker,source_text)
        result[speaker]={
            "score":score(clean,selected),
            "excluded_exact_text_overlap":len(excluded),
            "excluded_ids":excluded,
            "synthetic_only":True,
            "test_speaker_not_used_in_training":True,
            "test_speaker_related_to_validation_synthesis":
                speaker=="aleksandr-hq"
        }
        print("V3_DISJOINT_HELDOUT",speaker,
              json.dumps(result[speaker],ensure_ascii=False),flush=True)
    report={
        "schema":"monika_mww_v3_synthetic_independent_test_v1",
        "model_sha256":model_digest,
        "threshold_locked_on":"aleksandr_validation",
        "selection":val_report["gate"],"cutoff":selected,
        "human_trials":0,"real_false_wake_rate_per_hour":None,
        "hardware_installed":False,"acoustic_ready":False,
        "paid_calls":0,"test":result,
        "real_audio":False,
        "test_phrases_exact_overlap_filtered":True,
    }
    (out/"final_heldout.json").write_text(
        json.dumps(report,ensure_ascii=False,indent=2),encoding="utf8")
    print("V3_SYNTHETIC_EVAL_COMPLETE",model_digest,flush=True)

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--model",type=Path,required=True)
    p.add_argument("--corpus",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    main(a.model,a.corpus,a.output)
