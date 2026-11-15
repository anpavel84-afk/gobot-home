"""Bounded hard-negative mining on public TRAIN voices, never held-out/person audio."""
import os
os.environ['TF_NUM_INTRAOP_THREADS']='2';os.environ['TF_NUM_INTEROP_THREADS']='1'
import argparse,hashlib,json
from pathlib import Path
import numpy as np
import tensorflow as tf
from train import features,channel


def main(corpus,model,output):
    config=json.loads((model/'config.json').read_text());metadata=json.loads((model/'model.json').read_text())
    speakers=tuple(config['training_speakers']);heldout=set(config['validation_speakers']+config['test_speakers'])
    if config['human_training'] is not False or set(speakers)&heldout or len(speakers)!=5:raise ValueError('Invalid public training split')
    blob=(model/'gobot.tflite').read_bytes()
    if hashlib.sha256(blob).hexdigest()!=metadata['sha256'] or metadata['context_frames']!=204:raise ValueError('Model provenance mismatch')
    pool=[]
    for speaker in speakers:
        manifest=corpus/speaker/'manifest.json'
        if hashlib.sha256(manifest.read_bytes()).hexdigest()!=config['corpus_manifest_sha256'][speaker]:raise ValueError('Mining corpus differs from pretrained source')
        for item in json.loads(manifest.read_text()):
            if item['label']!='negative':continue
            path=corpus/speaker/item['file']
            if Path(item['file']).name!=item['file'] or not item['synthetic'] or item['speaker']!=speaker or path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:raise ValueError('Invalid synthetic negative')
            pool.append(path)
    rng=np.random.default_rng(20261119);hard=[]
    for group in range(16):
        runtime=tf.lite.Interpreter(model_content=blob,num_threads=1,experimental_op_resolver_type=tf.lite.experimental.OpResolverType.BUILTIN_WITHOUT_DEFAULT_DELEGATES)
        runtime.allocate_tensors();inp=runtime.get_input_details()[0];out=runtime.get_output_details()[0];parts=[rng.normal(0,60,40000)]
        for _ in range(42):
            raw=channel(np.fromfile(pool[int(rng.integers(len(pool)))],'<i2').astype(float),rng)
            parts.extend([np.zeros(int(rng.integers(1000,24000))),raw])
        wave=np.concatenate(parts);wave+=rng.normal(0,float(rng.uniform(0,300)),len(wave));rows=features(np.clip(wave,-32768,32767))
        q=np.clip(np.rint(rows/inp['quantization'][0])+inp['quantization'][1],-128,127).astype(np.int8);last=-100
        for i in range(0,len(q)-3,3):
            runtime.set_tensor(inp['index'],q[None,i:i+3]);runtime.invoke();end=i+4
            if end>=204 and i-last>15 and int(runtime.get_tensor(out['index'])[0,0])>=64:
                hard.append(rows[end-204:end].astype(np.float16));last=i
        print(json.dumps({'mined_groups':group+1,'hard_windows':len(hard)}),flush=True)
    if not hard:raise ValueError('No reproducible training hard negatives')
    np.save(output,np.stack(hard))
    report={'synthetic_only':True,'training_speakers':speakers,'excluded_speakers':sorted(heldout),'source_model_sha256':metadata['sha256'],'windows':len(hard),'context_frames':204,
        'sha256':hashlib.sha256(output.read_bytes()).hexdigest(),'groups':16,'paid_calls':0,'stream_offline_alignment_frames':1}
    output.with_suffix('.json').write_text(json.dumps(report,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('corpus',type=Path);p.add_argument('model',type=Path);p.add_argument('output',type=Path);a=p.parse_args();main(a.corpus,a.model,a.output)
