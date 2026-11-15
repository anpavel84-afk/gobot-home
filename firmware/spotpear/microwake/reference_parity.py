"""Public-only full-frame offline/streaming alignment diagnostic, not acceptance."""
import os
os.environ['TF_NUM_INTRAOP_THREADS']='2';os.environ['TF_NUM_INTEROP_THREADS']='1'
import argparse,json
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import tensorflow as tf
from microwakeword.mixednet import model
from train import features


def main(corpus,output):
    flags=SimpleNamespace(pointwise_filters='64,64,64,64',repeat_in_block='1,1,1,1',mixconv_kernel_sizes='[5],[7,11],[9,15],[23]',
        residual_connection='0,0,0,0',first_conv_filters=32,first_conv_kernel_size=5,stride=3,max_pool=False,pooled=False,spatial_attention=False)
    offline=model(flags,(204,40),128);offline.load_weights(output/'best.weights.h5')
    clips=sorted((corpus/'aleksandr').glob('positive*.pcm'))[:3]+sorted((corpus/'aleksandr').glob('negative*.pcm'))[:12]
    rng=np.random.default_rng(1527);parts=[]
    for path in clips:
        clip=np.fromfile(path,'<i2');parts.extend([rng.normal(0,30,16000),clip,rng.normal(0,30,16000)])
    rows=features(np.clip(np.concatenate(parts),-32768,32767).astype('<i2'))
    module=tf.saved_model.load(str(output/'saved'));streamed=[]
    for i in range(0,len(rows)-2,3):streamed.append(float(np.asarray(module.serve(rows[None,i:i+3]))[0,0]))
    comparisons={}
    for lag in range(-3,4):
        ends=np.arange(207,len(streamed)*3-3,3)+lag
        predictions=[]
        for at in range(0,len(ends),128):
            group=ends[at:at+128];batch=np.zeros((128,204,40),np.float32)
            for j,end in enumerate(group):batch[j]=rows[end-204:end]
            predictions.extend(np.asarray(offline(batch,training=False)).reshape(-1)[:len(group)])
        target=np.asarray(streamed)[68:68+len(ends)];difference=np.abs(np.asarray(predictions)-target)
        comparisons[str(lag)]={'max_error':float(difference.max()),'mean_error':float(difference.mean()),'different_decision_fraction':float(np.mean((np.asarray(predictions)>.9)!=(target>.9)))}
    result={'public_only':True,'frame_comparisons':len(ends),'alignment_offsets_frames':comparisons,'best_offset_frames':min(comparisons,key=lambda lag:comparisons[lag]['mean_error']),
        'note':'Measured alignment offsets are diagnostic; no thresholds or acceptance gates changed.'}
    (output/'parity-report.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('corpus',type=Path);p.add_argument('output',type=Path);a=p.parse_args();main(a.corpus,a.output)
