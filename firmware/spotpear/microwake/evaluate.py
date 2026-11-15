"""Streaming validation and untouched test, including transitions and long silence/noise."""
import json
import hashlib
import sys
from pathlib import Path

import numpy as np
import tensorflow as tf
from train import features, STRIDE, SEED

def traces(model, corpus, seed,kernel='desktop_optimized'):
    rng = np.random.default_rng(seed)
    all_files = list(sorted(corpus.glob("*.pcm")))
    rng.shuffle(all_files)
    chunks, spans = [], []
    n = 0
    for path in all_files:
        speech = np.fromfile(path, "<i2")
        padded = np.concatenate([np.zeros(12800), speech * rng.uniform(.35, 1.15), np.zeros(14400)])
        padded += rng.normal(0,rng.uniform(0,45),len(padded))
        chunks.append(np.clip(padded, -32768, 32767).astype("<i2"))
        spans.append((n, n+len(padded),path.name))
        n += len(padded)
    # Same frontend and interpreter continuously through clip boundaries.
    return trace_audio(model,np.concatenate(chunks),kernel=kernel), spans

def trace_audio(model,audio,kernel='desktop_optimized'):
    if kernel not in ('desktop_optimized','native_reference'):raise ValueError('Unknown inference baseline')
    source={'model_content':model} if isinstance(model,bytes) else {'model_path':str(model)}
    resolver=tf.lite.experimental.OpResolverType.BUILTIN_REF if kernel=='native_reference' else tf.lite.experimental.OpResolverType.BUILTIN_WITHOUT_DEFAULT_DELEGATES
    interpreter = tf.lite.Interpreter(**source, num_threads=1,experimental_op_resolver_type=resolver)
    interpreter.allocate_tensors()
    inp, out = interpreter.get_input_details()[0], interpreter.get_output_details()[0]
    if tuple(inp['shape'])!=(1,3,40) or inp['dtype']!=np.int8 or out['dtype']!=np.uint8:raise ValueError('Unsupported native KWS contract')
    scale, zero = inp["quantization"]
    frames = features(audio)
    q = np.clip(np.rint(frames / scale) + zero, -128,127).astype(np.int8)
    probs = []
    for i in range(0,len(q)-STRIDE+1, STRIDE):
        interpreter.set_tensor(inp["index"], q[None, i:i+STRIDE])
        interpreter.invoke()
        probs.append(int(interpreter.get_tensor(out["index"])[0,0]))
    frames.fill(0);q.fill(0)
    return np.array(probs)

def score(traces, cutoff, window=3,warmup=25):
    scores,spans=traces
    smooth=np.convolve(scores,np.ones(window)/window,mode="full")[:len(scores)]
    hits=np.flatnonzero(smooth >= cutoff)
    events=[]
    for i in hits:
        if i<warmup-1:continue
        if not events or i-events[-1] >= 50:
            events.append(i)
    times=np.array(events)*480+800
    tp=fp=positives=negatives=0
    mistakes=[]
    for start,end,name in spans:
        present=int(np.count_nonzero((times >= start) & (times < end)))
        if name.startswith("positive"):
            tp += bool(present)
            positives += 1
            if not present:
                mistakes.append(name)
        else:
            negatives += 1
            fp += present
            if present:
                mistakes.append(name)
    return dict(tp=int(tp),positive=positives,false_events=fp,negative=negatives,
                stream_seconds=spans[-1][1]/16000,mistakes=mistakes)
def main(root,out):
    model=out/"gobot.tflite"
    val=traces(model,root/"dmitri",SEED+24)
    sweep={c:score(val,c) for c in (178,191,204,216,229,242,250)}
    passing=[c for c,m in sweep.items() if m["false_events"] == 0 and m["tp"] >= .8*m["positive"]]
    chosen = min(passing) if passing else min(sweep,key=lambda c:(sweep[c]["false_events"],-sweep[c]["tp"],c))
    test=score(traces(model,root/"elena",SEED+25),chosen)
    report=dict(validation=sweep,cutoff=chosen,window=3,validation_passed=bool(passing),test=test,
                candidate_passed=bool(passing and test["false_events"] == 0 and test["tp"] >= .8*test["positive"]),
                human_trials=0,sha256=hashlib.sha256(model.read_bytes()).hexdigest())
    (out/"stream-report.json").write_text(json.dumps(report,indent=2))
    print(chosen,sweep[chosen],test)
if __name__=="__main__":
    main(Path(sys.argv[1]),Path(sys.argv[2]))
