"""Public-only complete-word guard experiment, not production qualification.

TRAIN-only calibration; an overlap rejects the experiment rather than lowering
the acceptance requirement. Local private queries need no compiler or upload.
"""
import argparse,ctypes,hashlib,json,time
from pathlib import Path
import numpy as np

SPEAKERS=('denis','dmitri','espeak-ru','anna','irina')
COEFFICIENTS=np.cos(np.pi*(np.arange(40)+.5)[None,:]*np.arange(1,13)[:,None]/40).astype(np.float32)


def features(pcm):
    from pymicro_features import MicroFrontend
    front=MicroFrontend();rows=[]
    for at in range(0,len(pcm)-159,160):
        row=front.process_samples(pcm[at:at+160].astype('<i2').tobytes())
        if row.samples_read!=160:raise ValueError('Frontend dropped input')
        if row.features:rows.append(row.features)
    return np.asarray(rows,np.float32)


def vectors(rows):
    result=np.asarray(rows,np.float32)@COEFFICIENTS.T
    result/=np.maximum(np.linalg.norm(result,axis=1,keepdims=True),1e-6)
    return np.ascontiguousarray(result,np.float32)


def scores(models,query,recent=None):
    """NumPy reference matching the bounded C++ DP; no data persistence."""
    k,t,d=models.shape;n=len(query);recent=n if recent is None else recent
    if not (1<=k<=128 and 4<=t<=128 and 1<=d<=40 and 1<=n<=2000):raise ValueError('Unbounded acoustic query')
    old=np.full((k,t+1),np.inf,np.float32);old[:,0]=0;older=old.copy();previous_start=np.zeros((k,t+1),np.int32);older_start=previous_start.copy();last_cost=np.zeros((k,t),np.float32);best=np.full(k,np.inf,np.float32)
    for j,frame in enumerate(query):
        current=np.full_like(old,np.inf);current[:,0]=0;starts=np.zeros_like(previous_start);starts[:,0]=j
        costs=np.maximum(0,1-np.minimum(1,np.sum(models*frame[None,None,:],axis=2)))
        for i in range(1,t+1):
            v=old[:,i-1]+2*costs[:,i-1];first=np.full(k,j,np.int32) if i==1 else previous_start[:,i-1].copy()
            if i>=2:
                alternative=old[:,i-2]+costs[:,i-2]+2*costs[:,i-1];choose=alternative<v;v=np.where(choose,alternative,v)
                first=np.where(choose,j if i==2 else previous_start[:,i-2],first)
            if j>=1:
                alternative=older[:,i-1]+last_cost[:,i-1]+2*costs[:,i-1];choose=alternative<v;v=np.where(choose,alternative,v)
                first=np.where(choose,j-1 if i==1 else older_start[:,i-1],first)
            current[:,i]=v;starts[:,i]=first
        duration=j-starts[:,t]+1
        if j>=n-recent:best=np.minimum(best,np.where((duration>=20)&(duration<=160),current[:,t]/(t+duration),np.inf))
        older=old;older_start=previous_start;old=current;previous_start=starts;last_cost=costs
    return best


def native_scores(lib,models,query):
    models=np.ascontiguousarray(models,np.float32);query=np.ascontiguousarray(query,np.float32);result=np.empty(len(models),np.float32)
    ptr=ctypes.POINTER(ctypes.c_float)
    code=lib.word_guard_scores(models.ctypes.data_as(ptr),len(models),models.shape[1],models.shape[2],query.ctypes.data_as(ptr),len(query),len(query),20,160,result.ctypes.data_as(ptr))
    if code:raise ValueError('Native guard rejected bounded inputs')
    return result


def prepare(corpus,output,library):
    if output.exists():raise ValueError('New experiment directory required')
    templates=[];owners=[];positive=[];negative=[];provenance=[]
    for speaker in SPEAKERS:
        entries=json.loads((corpus/speaker/'manifest.json').read_text())
        for item in entries:
            path=corpus/speaker/item['file']
            if path.is_symlink() or Path(item['file']).name!=item['file'] or not item.get('synthetic') or item['speaker']!=speaker or hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:raise ValueError('Unverified public source')
            if item['label']=='negative':negative.append(path);continue
            if ',' in item['text']:continue
            positive.append((path,speaker))
            if not path.name.endswith('-100.pcm'):continue
            pcm=np.fromfile(path,'<i2');active=np.flatnonzero(np.abs(pcm.astype(np.int32))>max(20,np.max(np.abs(pcm.astype(np.int32)))*.025))
            if not len(active):raise ValueError('Empty public keyword')
            a=max(0,int(active[0])-160);b=min(len(pcm),int(active[-1])+321)
            rows=features(np.concatenate([np.zeros(32000,dtype='<i2'),pcm,np.zeros(1600,dtype='<i2')]))
            clip=vectors(rows[max(0,200+a//160-2):200+(b+159)//160-2])
            resized=np.stack([np.interp(np.linspace(0,len(clip)-1,80),np.arange(len(clip)),clip[:,d]) for d in range(12)],axis=1).astype(np.float32)
            resized/=np.maximum(np.linalg.norm(resized,axis=1,keepdims=True),1e-6)
            templates.append(resized);owners.append(speaker);provenance.append({'speaker':speaker,'file':path.name,'sha256':item['sha256']})
    if len(templates)!=25 or len(positive)!=75 or len(negative)!=2490:raise ValueError('Unexpected TRAIN inventory')
    models=np.stack(templates);lib=ctypes.CDLL(str(library.resolve()));deadline=time.monotonic()+600
    def query(path):return vectors(features(np.concatenate([np.zeros(32000,dtype='<i2'),np.fromfile(path,'<i2'),np.zeros(8000,dtype='<i2')])))
    pos=[float(native_scores(lib,models[np.asarray(owners)!=speaker],query(path)).min()) for path,speaker in positive]
    rng=np.random.default_rng(20261115);rng.shuffle(negative);neg=[];early=False
    for index,path in enumerate(negative):
        if time.monotonic()>deadline:raise TimeoutError('Bounded public guard experiment expired')
        neg.append(float(native_scores(lib,models,query(path)).min()))
        if (index+1)%128==0:
            threshold=min(1.,min(neg))-1e-5;recall=float(np.mean(np.asarray(pos)<=threshold))
            print(json.dumps({'negative_clips':index+1,'leave_one_train_voice_out_recall':recall,'threshold':threshold}),flush=True)
            if recall<.9:early=True;break # More negatives cannot restore this separation.
    threshold=min(1.,min(neg))-1e-5;recall=float(np.mean(np.asarray(pos)<=threshold))
    output.mkdir();np.save(output/'templates.npy',models)
    result={'synthetic_only':True,'personal_training':False,'training_speakers':SPEAKERS,'excluded_speakers':['aleksandr','elena'],
        'templates':provenance,'positive_clips':len(pos),'negative_clips':len(neg),'minimum_negative_distance':min(neg),'threshold':threshold,
        'leave_one_train_voice_out_recall':recall,'early_rejection':early,'calibration_passed':recall>=.9 and len(neg)==2490,'product_accepted':False,'paid_calls':0}
    (output/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps({k:v for k,v in result.items() if k!='templates'}))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('corpus',type=Path);p.add_argument('output',type=Path);p.add_argument('library',type=Path)
    a=p.parse_args();prepare(a.corpus,a.output,a.library)
