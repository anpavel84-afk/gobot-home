"""Count events in a continuous synthetic negative stream; never opens a microphone."""
import json
import hashlib
import sys
from pathlib import Path
import numpy as np
import tensorflow as tf
from pymicro_features import MicroFrontend

def run(model, negative_dir, minutes=30):
    report=json.loads((model/"stream-report.json").read_text())
    cutoff=report["cutoff"]
    it=tf.lite.Interpreter(model_path=str(model/"gobot.tflite"), num_threads=1,
        experimental_op_resolver_type=tf.lite.experimental.OpResolverType.BUILTIN_WITHOUT_DEFAULT_DELEGATES)
    it.allocate_tensors()
    inp,out=it.get_input_details()[0],it.get_output_details()[0]
    scale,zero=inp["quantization"]
    frontend=MicroFrontend()
    rng=np.random.default_rng(885377)
    clips=[np.fromfile(p,"<i2") for p in sorted(negative_dir.glob("negative-*.pcm"))]
    total=minutes*60*16000
    cursor=0
    smooth=[0,0,0]
    predictions=events=0
    unlocked=0
    features=[]
    while cursor<total:
        speech=clips[rng.integers(len(clips))].astype(float)*rng.uniform(.08,.9)
        quiet=rng.integers(4000,68000)
        signal=np.pad(speech,(quiet,0))
        t=np.arange(len(signal))/16000
        signal+=rng.uniform(0,300)*np.sin(2*np.pi*60*t)+rng.normal(0,rng.uniform(0,90),len(signal))
        signal=np.clip(signal,-32768,32767).astype("<i2")
        for i in range(0,min(len(signal),total-cursor)-159,160):
            row=frontend.process_samples(signal[i:i+160].tobytes()).features
            cursor+=160
            if not row: continue
            features.append(row)
            if len(features)!=3: continue
            q=np.clip(np.rint(np.array(features,np.float32)/scale)+zero,-128,127).astype(np.int8)
            it.set_tensor(inp["index"],q[None])
            it.invoke()
            smooth[predictions%3]=int(it.get_tensor(out["index"])[0,0])
            predictions+=1
            if cursor>=unlocked and sum(smooth)>=3*cutoff:
                events+=1
                unlocked=cursor+24000
            features.clear()
    result=dict(kind="synthetic confusables with generated hum, silence and noise",seconds=cursor/16000,
                false_events=events,false_per_hour=events*3600/(cursor/16000),real_household_seconds=0,
                model_sha256=hashlib.sha256((model/'gobot.tflite').read_bytes()).hexdigest())
    (model/"ambient.json").write_text(json.dumps(result,indent=2))
    print(result)
if __name__=="__main__":
    run(Path(sys.argv[1]),Path(sys.argv[2]))
