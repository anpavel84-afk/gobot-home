"""Fixed-policy PLAN-only validation of encrypted candidates; no paid calls.

Run with the existing project-private TensorFlow Python. No model/audio output,
no training, no export to build hosts; all detailed reports stay Owner-private.
"""
import argparse,hashlib,io,json,sys,time,wave
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(Path(__file__).parent),str(ROOT/'services/brain'),str(ROOT/'data/hardware/gobot-v1/mww-inputs/mww')]
import numpy as np
from gobot.secrets_store import _dpapi
from sample_retention import paths,candidate_path
from evaluate import trace_audio,traces,score
from parity import fingerprint

def main(ident,sha=None):
    p,meta=paths(ident);metadata=json.loads(meta.read_text())
    if time.time()>=metadata['expires_at']:raise ValueError('Sample expired')
    if metadata.get('capture_domain')!='mono_pcm16_pre_afe':raise ValueError('Wrong capture domain')
    assert fingerprint()==(98,1987024791)
    model_path=candidate_path(ident,sha) if sha else p.with_name(ident+'-personal-model.dpapi')
    blob=_dpapi(model_path.read_bytes(),decrypt=True);sha=hashlib.sha256(blob).hexdigest()
    report_path=candidate_path(ident,sha).with_suffix('.json')
    if not report_path.exists():report_path=p.with_name(ident+'-neural-pilot.json')
    evidence=json.loads(report_path.read_text())
    if evidence['model_sha256']!=sha:raise ValueError('Candidate/evidence mismatch')
    warmup=max(25,(int(evidence.get('context_frames',75))+2)//3)
    raw=bytearray(_dpapi(p.read_bytes(),decrypt=True));pcm=None
    try:
        with wave.open(io.BytesIO(raw)) as w:
            if (w.getframerate(),w.getnchannels(),w.getsampwidth())!=(16000,1,2):raise ValueError('Invalid PCM')
            pcm=np.frombuffer(w.readframes(w.getnframes()),'<i2').copy()
        cutoff=int(evidence.get('cutoff',250));window=int(evidence.get('window',3))
        if window not in (3,10) or not 1<=cutoff<=255:raise ValueError('Unsupported native decision policy')
        probs=trace_audio(blob,pcm);smooth=np.convolve(probs,np.ones(window)/window,mode='full')[:len(probs)];events=[]
        for i in np.flatnonzero(smooth>=cutoff):
            if i>=warmup-1 and (not events or i-events[-1]>=50):events.append(int(i))
        result={'model_sha256':sha,'warmup_invocations':warmup,'cutoff':cutoff,'window':window,'human_labels_verified':False,
            'capture_domain':'mono_pcm16_pre_afe','private_event_seconds':[round(i*.03+.05,2) for i in events],
            'provider_calls':0,'installed':False,'product_accepted':False}
        reference=evidence.get('base_profile')=='reference'
        for speaker,seed in [('aleksandr' if reference else 'dmitri',7635),('elena',7882)]:
            directory=ROOT/f'data/hardware/gobot-v1/kws/{"original-training" if speaker=="aleksandr" else "reference-validation"}/{speaker}'
            manifest=json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
            for item in manifest:
                name=item['file']
                if Path(name).name!=name or item['speaker']!=speaker or not item['synthetic']:raise ValueError('Reference manifest mismatch')
                if hashlib.sha256((directory/name).read_bytes()).hexdigest()!=item['sha256']:raise ValueError('Reference hash mismatch')
            metric=score(traces(blob,directory,seed),cutoff,window=window,warmup=warmup);result[speaker]=metric
            print(json.dumps({'synthetic_reference':speaker,**{k:v for k,v in metric.items() if k!='mistakes'}}),flush=True)
        p.with_name(ident+'-'+sha[:12]+'-validation.json').write_text(json.dumps(result,indent=2))
        print(json.dumps({'private_sample_events':len(events),'warmup':warmup,'product_accepted':False}),flush=True)
    finally:
        raw[:]=bytes(len(raw))
        if pcm is not None:pcm.fill(0)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('sample_id');parser.add_argument('--candidate');a=parser.parse_args();main(a.sample_id,a.candidate)
