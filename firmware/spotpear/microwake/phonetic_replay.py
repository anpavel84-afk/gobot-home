"""PUBLIC TRAIN whole-name/partial-name contrast; no owner audio or new TTS."""
import argparse,hashlib,json,time
from pathlib import Path
import numpy as np
import train_reference as reference
from augmentation import trim_background
from public_data_scope import public_training_scope


def fragment(raw,rng):
    voiced=trim_background(raw.astype(float))
    if len(voiced)<640:raise ValueError('Insufficient public speech for a partial name')
    length=max(160,int(len(voiced)*rng.uniform(.25,.45)))
    return voiced[:length].copy() if rng.random()<.5 else voiced[-length:].copy()


def main(corpus,source,output):
    config=json.loads((source/'config.json').read_text());speakers=['denis','dmitri','espeak-ru','anna','irina']
    if not public_training_scope(config) or config.get('training_speakers')!=speakers:raise ValueError('Public TRAIN sources required')
    rng=np.random.default_rng(20261121);normal=[];aliases=[]
    for speaker in speakers:
        path=corpus/speaker/'manifest.json'
        if hashlib.sha256(path.read_bytes()).hexdigest()!=config['corpus_manifest_sha256'][speaker]:raise ValueError('Changed public corpus')
        for row in json.loads(path.read_text()):
            if row['label']!='positive':continue
            name=row['file'];file=corpus/speaker/name
            if Path(name).name!=name or file.is_symlink() or row.get('speaker')!=speaker or row.get('synthetic') is not True:raise ValueError('Unsafe source')
            (aliases if name.startswith('positive-gabot-') else normal).append((file,row['sha256']))
    if len(aliases)!=1000 or len(normal)!=50000:raise ValueError('Incomplete positive inventory')
    selected=aliases+[normal[int(i)] for i in rng.choice(len(normal),1000,replace=False)]
    if output.exists() or output.with_suffix('.json').exists():raise ValueError('Never overwrite phonetic evidence')
    x=np.lib.format.open_memmap(output,mode='w+',dtype=np.float16,shape=(8000,204,40));reference.WORD_ANCHORED=True;reference.TAIL_SAMPLES=9600
    val_groups=np.concatenate([rng.choice(1000,100,replace=False),1000+rng.choice(1000,100,replace=False)])
    started=time.monotonic()
    for group,(file,sha) in enumerate(selected):
        if time.monotonic()-started>1800:raise RuntimeError('Public feature generation time cap')
        raw=np.fromfile(file,'<i2')
        if hashlib.sha256(raw.tobytes()).hexdigest()!=sha:raise ValueError('Changed source PCM')
        for variant in range(2):
            row=group*4+variant*2
            x[row]=reference.window(raw,rng,True,quiet=True)
            x[row+1]=reference.window(fragment(raw,rng),rng,False,quiet=True)
        if (group+1)%200==0:print(json.dumps({'phonetic_groups':group+1,'total':2000}),flush=True)
    x.flush()
    output.with_suffix('.json').write_text(json.dumps({'schema':'public-whole-partial-replay-v1','synthetic_only':True,'training_speakers':speakers,'excluded_speakers':['aleksandr','elena'],'groups':2000,'rows':8000,'positive_rows':4000,'alias_groups':1000,'rows_per_group':4,'validation_groups':val_groups.tolist(),'split_unit':'source clip, no shared training/validation source','corpus_manifest_sha256':config['corpus_manifest_sha256'],'sha256':hashlib.sha256(output.read_bytes()).hexdigest(),'frontend_hop_samples':160,'context_frames':204,'positive_word_preserved':True,'paid_calls':0}))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('corpus','source','output'):p.add_argument(key,type=Path)
    a=p.parse_args();main(a.corpus,a.source,a.output)
