"""Add explicit Gabot pronunciation to verified PUBLIC corpus, without rewriting it."""
import argparse,hashlib,json,os,time
from pathlib import Path
import numpy as np
from full_corpus import SPEAKERS,voice_for,synthesize
from wake_variants import GABOT_VARIANTS


def alias_plan(speaker,heldout=False):
    allowed=('aleksandr','elena') if heldout else SPEAKERS
    if speaker not in allowed:raise ValueError('Alias speaker split mismatch')
    rng=np.random.default_rng(20261115+allowed.index(speaker)+(100 if heldout else 0))
    rows=[]
    for index in range(20 if heldout else 200):
        rows.append({'file':f'positive-gabot-{index:04}.pcm','text':GABOT_VARIANTS[index%2],
            'speaker':speaker,'synthetic':True,'label':'positive','speed':int(rng.integers(70,131)),
            'pitch':int(rng.integers(-20,21)),'noise_scale':float(rng.uniform(.35,1)),
            'noise_w_scale':float(rng.uniform(.5,1.2))})
    return rows


def main(stage,base,out,heldout):
    stage=stage.resolve();base=base.resolve();out=out.resolve();heldout=heldout.resolve()
    if any(p==stage or not p.is_relative_to(stage) for p in (base,out,heldout)) or len({base,out,heldout})!=3:raise ValueError('Use isolated public stage directories')
    complete=json.loads((base/'complete.json').read_text());provenance=json.loads((base/'provenance.json').read_text())
    if complete.get('clips')!=60000 or complete.get('ready_for_feature_extraction') is not True or provenance.get('schema')!='gobot-full-tts-v1' or provenance.get('speakers')!=list(SPEAKERS):raise ValueError('Incomplete public base')
    out.mkdir();heldout.mkdir();started=time.monotonic()
    for speaker in (*SPEAKERS,'aleksandr','elena'):
        test=speaker not in SPEAKERS;target=(heldout if test else out)/speaker;target.mkdir();rows=[]
        if not test:
            entries=json.loads((base/speaker/'manifest.json').read_text())
            if len(entries)!=12000:raise ValueError('Incomplete base voice')
            for row in entries:
                name=row['file'];source=base/speaker/name
                if Path(name).name!=name or source.is_symlink() or row.get('synthetic') is not True or row.get('speaker')!=speaker or hashlib.sha256(source.read_bytes()).hexdigest()!=row['sha256']:raise ValueError('Changed public base')
                os.link(source,target/name);rows.append(row)
        voice=voice_for(stage,speaker)
        for task in alias_plan(speaker,test):
            if time.monotonic()-started>1800:raise RuntimeError('Alias generation time limit reached')
            pcm=synthesize(task,voice,stage,out);raw=pcm.tobytes();(target/task['file']).write_bytes(raw)
            rows.append({**task,'sha256':hashlib.sha256(raw).hexdigest(),'samples':len(pcm)})
        (target/'manifest.json').write_text(json.dumps(rows,ensure_ascii=False),encoding='utf-8')
        print(json.dumps({'alias_voice_complete':speaker,'heldout':test,'new_clips':20 if test else 200,'paid_calls':0}),flush=True)
    (out/'provenance.json').write_text(json.dumps({**provenance,'schema':'gobot-full-tts-alias-v1','positive_per_voice':10200,'positive_total':51000,'alias_positive_total':1000,'alias_forms':GABOT_VARIANTS,'base_provenance_sha256':hashlib.sha256((base/'provenance.json').read_bytes()).hexdigest()}))
    (out/'complete.json').write_text(json.dumps({'clips':61000,'ready_for_feature_extraction':True,'paid_calls':0}))
    (heldout/'provenance.json').write_text(json.dumps({'synthetic_only':True,'evaluation_only':True,'speakers':['aleksandr','elena'],'excluded_training_speakers':list(SPEAKERS),'positive_per_voice':20,'paid_calls':0}))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('stage','base','output','heldout'):p.add_argument(key,type=Path)
    a=p.parse_args();main(a.stage,a.base,a.output,a.heldout)
