"""Independent synthetic voice evaluation of exported streaming INT8 Monika microWakeWord.

Threshold selected ONLY on validation speaker Aleksandr, locked BEFORE
the separate held-out test speaker Elena. Raw speech never leaves local stage.
This does NOT mean real human acceptance or a false-wake/hr home measurement.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path

os.environ.setdefault("CUDA_VISIBLE_DEVICES","-1")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL","2")
os.environ.setdefault("TF_NUM_INTRAOP_THREADS","2")
import numpy as np
import tensorflow as tf
from train_monika import features

SR=16000
FRAME_HOP=160
BLOCK=3
WIN=5
MIN_SPACING=50   # ~1.5 sec between accepted events; independent trials reset
CUTOFFS=[128,153,178,191,204,216,229,235,242,248,251]

def voiced_files(corpus:Path,speaker:str,label:str):
    directory=corpus/speaker
    data=json.loads((directory/f"manifest-{label}.json").read_text(encoding="utf8"))
    for row in data:
        f=directory/row["file"]
        if row["speaker"]!=speaker or row["label"]!=label \
                or row["split"] not in ("validation","test") or f.name!=row["file"] \
                or hashlib.sha256(f.read_bytes()).hexdigest()!=row["sha256"]:
            raise ValueError("heldout_manifest_integrity_failure")
        yield row, np.fromfile(f,dtype="<i2")

def stream_trace(interpreter, inp, out, raw):
    # Each independent clip gets a fresh clean streaming RNN state.
    interpreter.reset_all_variables()
    # Prefix and suffix allow native microfeature window ramp-up; no
    # concatenated clips or target leakage across trial boundaries.
    raw=np.concatenate([np.zeros(int(.38*SR),dtype="<i2"),raw,
                        np.zeros(int(.9*SR),dtype="<i2")])
    feat=features(raw)
    scale,zero=inp["quantization"]
    q=np.clip(np.rint(feat/scale)+zero,-128,127).astype("int8")
    stream=[]
    for start in range(0,len(q)-BLOCK+1,BLOCK):
        interpreter.set_tensor(inp["index"],q[None,start:start+BLOCK])
        interpreter.invoke()
        stream.append(int(interpreter.get_tensor(out["index"])[0,0]))
    return np.asarray(stream,dtype=np.int16),len(raw)/SR

def classify(scores,cutoff,window=WIN):
    if len(scores)==0:return 0
    smoothed=np.convolve(scores,np.ones(window)/window,"full")[:len(scores)]
    detected=np.flatnonzero(smoothed>=cutoff)
    events=[]
    for idx in detected:
        if idx<8:continue  # startup filter, not annotated word end
        if not events or idx-events[-1]>MIN_SPACING:
            events.append(int(idx))
    return len(events)

def evaluation(model:Path, corpus:Path, speaker:str):
    decoder=tf.lite.Interpreter(model_path=str(model),num_threads=1,
       experimental_op_resolver_type=tf.lite.experimental.OpResolverType.BUILTIN_REF)
    decoder.allocate_tensors()
    inp,out=decoder.get_input_details()[0],decoder.get_output_details()[0]
    if tuple(inp["shape"])!=(1,3,40) or inp["dtype"]!=np.int8 \
        or out["dtype"]!=np.uint8:
        raise ValueError("unsupported_stream_int8")
    runs=[]
    for label in ("positive","negative"):
        for row,audio in voiced_files(corpus,speaker,label):
            outputs,duration=stream_trace(decoder,inp,out,audio)
            runs.append({"label":label,"speaker":speaker,
                         "source_sha256":row["sha256"],
                         "outputs":outputs,"duration_s":round(duration,3),
                         "name_for_error_only":row["file"]})
        print("EVAL_DECODED",speaker,label,
              sum(r["label"]==label for r in runs),flush=True)
    return runs

def score(runs,cutoff:int):
    positive=sum(r["label"]=="positive" for r in runs)
    negative=len(runs)-positive
    detected=0;missed=[]
    false_events=0;negative_duration=0.
    for r in runs:
        count=classify(r["outputs"],cutoff)
        if r["label"]=="positive":
            detected+=int(count>0)
            if count==0:missed.append(r["name_for_error_only"])
        else:
            negative_duration+=r["duration_s"]
            false_events+=count
    return {"positive":positive,"detected":detected,"misses":positive-detected,
            "negative":negative,"false_events":false_events,
            "negative_duration_s":round(negative_duration,2),
            "synthetic_false_events_per_hour":(
                round(3600*false_events/negative_duration,2)
                if negative_duration>=1800 else None),
            "not_real_household_audio":True,
            "missed_heldout_ids":missed}

def main(model:Path,corpus:Path,out:Path):
    if out.exists():
        raise ValueError("no_overwrite_evaluation_output")
    out.mkdir(parents=True)
    if model.name!="monika_int8.tflite":raise ValueError("wrong_target_model")
    selected_model_sha=hashlib.sha256(model.read_bytes()).hexdigest()
    validation=evaluation(model,corpus,"aleksandr")
    sweep={str(c):score(validation,c) for c in CUTOFFS}
    # A validation minimum of 65% recall and 0 observed false events is
    # deliberately conservative. If impossible, retain the FAIL verdict.
    eligible=[c for c in CUTOFFS if sweep[str(c)]["detected"]>=.65*sweep[str(c)]["positive"]
                              and sweep[str(c)]["false_events"]==0]
    if eligible:
        cutoff=min(eligible)
        gate="VALIDATION_ONLY_THRESHOLDS_PASS_IN_SYNTHETIC"
    else:
        cutoff=min(CUTOFFS,key=lambda c:
                   (sweep[str(c)]["false_events"],
                    -sweep[str(c)]["detected"], c))
        gate="SYNTHETIC_VALIDATION_GATE_FAILED"
    (out/"validation_selection.json").write_text(json.dumps({
        "schema":"monika_mww_validation_threshold_v1",
        "model_sha256":selected_model_sha,
        "speaker":"aleksandr","selection_speaker_only":"aleksandr",
        "cutoff":cutoff,"window":WIN,"gate":gate,
        "sweep":sweep,"human_trials":0},ensure_ascii=False,indent=2))
    print("LOCKED_CUTOFF_BEFORE_TEST",cutoff,gate,flush=True)
    # The test speaker data is untouched up to here.
    separate_test=evaluation(model,corpus,"elena")
    result=score(separate_test,cutoff)
    report={"schema":"monika_mww_synthetic_heldout_v1",
        "model_sha256":selected_model_sha,"synthetic_only":True,"human_trials":0,
        "owner_audio_used":False,"real_false_wakes_per_hour":None,
        "name_end_to_ack_latency_p50_ms":None,
        "name_end_to_ack_latency_p95_ms":None,
        "threshold_fixed_on":"validation_speaker_aleksandr",
        "test_speaker":"elena","test_texts_disjoint_from_training_texts":True,
        "tflite_stream_inference_uint8_probabilities":True,
        "cutoff":cutoff,"window":WIN,"validation_gate":gate,
        "test":result,"installed_on_esp32":False,
        "product_accepted":False,"paid_calls":0}
    (out/"heldout_result.json").write_text(
        json.dumps(report,ensure_ascii=False,indent=2))
    print("HELDOUT_SYNTHETIC_ONLY",json.dumps(report,ensure_ascii=False),flush=True)

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--corpus",type=Path,required=True)
    p.add_argument("--model",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    main(args.model,args.corpus,args.output)
