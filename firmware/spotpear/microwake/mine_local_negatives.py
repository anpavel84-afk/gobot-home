"""PLAN-only hard examples: private detector, manifest-verified public TRAIN audio.

Never reads a new recording, uploads anything or includes held-out voices.
Only public clip identifiers/scores are retained locally, under source expiry.
"""
import argparse,bisect,hashlib,json,sys,time
from collections import deque
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'data/hardware/gobot-v1/local-wake-runtime'),str(ROOT/'services/brain')]
import numpy as np
from pymicro_features import MicroFrontend
from ai_edge_litert.interpreter import Interpreter,OpResolverType
from gobot.secrets_store import _dpapi
from sample_retention import paths,candidate_path
from original_replay import corpus

SPEAKERS=('denis','dmitri','espeak-ru','anna','irina')


def main(ident,sha,root):
    root=Path(root).resolve()
    if not root.is_relative_to(ROOT/'data'):raise ValueError('Local public corpus required')
    _,meta=paths(ident);consent=json.loads(meta.read_text())
    if consent['expires_at']<=time.time():raise ValueError('Source model expired')
    model_path=candidate_path(ident,sha)
    profile=json.loads(model_path.with_suffix('.json').read_text())
    if (profile.get('model_sha256')!=sha or profile.get('context_frames')!=204 or
        profile.get('window')!=10 or profile.get('cutoff')!=231):raise ValueError('Require exact full native private profile')
    blob=_dpapi(model_path.read_bytes(),decrypt=True)
    if hashlib.sha256(blob).hexdigest()!=sha:raise ValueError('Private model changed')
    _,negative=corpus(root,SPEAKERS) # Complete per-file hashes/labels; excludes A/E.
    ranks={};deadline=time.monotonic()+900;false_frames=0
    for speaker in SPEAKERS:
        files=[p for p in negative if p.parent.name==speaker]
        parts=[np.zeros(40000,dtype='<i2')];ends=[];cursor=40000
        for p in files:
            pcm=np.fromfile(p,'<i2');parts.extend([pcm,np.zeros(8000,dtype='<i2')])
            cursor+=len(pcm)+8000;ends.append(cursor)
        audio=np.concatenate(parts);del parts
        rt=Interpreter(model_content=blob,num_threads=1,experimental_op_resolver_type=OpResolverType.BUILTIN_REF)
        rt.allocate_tensors();inp=rt.get_input_details()[0];out=rt.get_output_details()[0]
        if tuple(inp['shape'])!=(1,3,40) or inp['dtype']!=np.int8 or out['dtype']!=np.uint8:raise ValueError('Unexpected native model contract')
        front=MicroFrontend();pending=[];history=deque(maxlen=10);calls=0
        for at in range(0,len(audio)-159,160):
            if at%160000==0 and (time.monotonic()>deadline or time.time()>=consent['expires_at']):raise TimeoutError('Bounded private mining expired')
            row=front.process_samples(audio[at:at+160].tobytes())
            if row.samples_read!=160:raise ValueError('Frontend input lost')
            if not row.features:continue
            pending.append(row.features)
            if len(pending)<3:continue
            q=np.clip(np.rint(np.asarray(pending,np.float32)/inp['quantization'][0])+inp['quantization'][1],-128,127).astype(np.int8)
            rt.set_tensor(inp['index'],q[None]);rt.invoke();pending.clear();calls+=1
            history.append(int(rt.get_tensor(out['index'])[0,0]))
            if calls<68 or len(history)<10 or at<40000:continue
            score=sum(history)/10
            if score>=231:false_frames+=1
            index=min(len(files)-1,bisect.bisect_right(ends,at+160))
            # Include the preceding public clip too: causal context can span it.
            for j in set([index,max(0,index-1)]):
                name=files[j].relative_to(root).as_posix();ranks[name]=max(ranks.get(name,0),score)
        audio.fill(0)
        print(json.dumps({'train_speaker_complete':speaker,'ranked_clips':len(ranks)}),flush=True)
    selected=sorted(((k,v) for k,v in ranks.items() if v>=64),key=lambda item:(-item[1],item[0]))[:128]
    if len(selected)<32:raise ValueError('Too few TRAIN hard examples; do not retry blindly')
    result={'kind':'private_teacher_public_train_negatives','synthetic_only':True,'source_sample':ident,'source_model_sha256':sha,
        'expires_at':consent['expires_at'],'training_speakers':SPEAKERS,'excluded_speakers':['aleksandr','elena'],
        'kernel_baseline':'native_reference','false_decision_frames':false_frames,'corpus_manifest_sha256':{s:hashlib.sha256((root/s/'manifest.json').read_bytes()).hexdigest() for s in SPEAKERS},
        'clips':[{'file':name,'score':score} for name,score in selected],'paid_calls':0,'recordings_read':0}
    if time.time()>=consent['expires_at']:raise ValueError('Source expired before saving mining report')
    target=meta.with_name(ident+'-mined-public-negatives.json');target.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({'selected_public_negatives':len(selected),'false_decision_frames':false_frames,'paid_calls':0}))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('sample');p.add_argument('candidate_sha');p.add_argument('public_corpus',type=Path)
    a=p.parse_args();main(a.sample,a.candidate_sha,a.public_corpus)
