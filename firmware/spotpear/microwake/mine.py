"""Mine *training voices only* from a continuous synthetic negative stream."""
from pathlib import Path
import sys
import json
import numpy as np
import tensorflow as tf
from train import features, STRIDE, FRAMES, SEED, channel

TRAIN=("denis","espeak-ru","anna","aleksandr")
def main(corpus, model, output):
    rng=np.random.default_rng(SEED+917)
    interp=tf.lite.Interpreter(model_path=str(model/"gobot.tflite"),num_threads=1)
    interp.allocate_tensors()
    inp,out=interp.get_input_details()[0],interp.get_output_details()[0]
    scale,zero=inp["quantization"]
    pool={v:sorted((corpus/v).glob("negative*.pcm")) for v in TRAIN}
    hard=[]
    easy=[]
    for group in range(68):
        clips=[]
        for i in range(42):
            speaker=TRAIN[rng.integers(len(TRAIN))]
            raw=np.fromfile(rng.choice(pool[speaker]),"<i2").astype(float)
            raw=channel(raw,rng)
            clips.extend((np.zeros(rng.integers(1000,24000)),raw))
        wave=np.concatenate(clips)
        wave+=rng.normal(0,rng.uniform(0,90),len(wave))
        f=features(np.clip(wave,-32768,32767))
        q=np.clip(np.rint(f/scale)+zero,-128,127).astype(np.int8)
        last=-999
        for i in range(0,len(q)-STRIDE+1,STRIDE):
            interp.set_tensor(inp["index"],q[None,i:i+STRIDE])
            interp.invoke()
            end=i+STRIDE
            if end<FRAMES: continue
            prob=int(interp.get_tensor(out["index"])[0,0])
            if i-last>15 and prob>=64:
                hard.append(f[end-FRAMES:end].copy());last=i
            elif rng.random()<.004:
                easy.append(f[end-FRAMES:end].copy())
    if not hard: raise ValueError("No reproducible false positives")
    np.save(output,np.stack(hard+easy))
    print(json.dumps(dict(hard=len(hard),background=len(easy),voices=TRAIN)))
if __name__=="__main__": main(*map(Path,sys.argv[1:]))
