"""PLAN-only encrypted sample evaluation. No audio/features or identifying text output."""
import argparse,hashlib,io,json,sys,time,wave
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'data/hardware/gobot-v1/local-wake-runtime'),str(ROOT/'services/brain')]
import numpy as np
from pymicro_features import MicroFrontend
from ai_edge_litert.interpreter import Interpreter,OpResolverType
from gobot.secrets_store import _dpapi
from sample_retention import paths,cleanup
from parity import fingerprint

def evaluate(ident,model,encrypted_model=False,model_sample_id=None):
    p,meta=paths(ident);metadata=json.loads(meta.read_text())
    if time.time()>=metadata['expires_at']:cleanup(ident);raise ValueError('Sample expired')
    assert fingerprint()==(98,1987024791)
    if encrypted_model:
        source,source_meta=paths(model_sample_id or ident)
        if time.time()>=json.loads(source_meta.read_text())['expires_at']:raise ValueError('Personal model expired')
        model_bytes=_dpapi(source.with_name((model_sample_id or ident)+'-personal-model.dpapi').read_bytes(),decrypt=True)
    else:model_bytes=model.read_bytes()
    model_sha=hashlib.sha256(model_bytes).hexdigest()
    context_frames=75
    if encrypted_model:
        report_path=source.with_name((model_sample_id or ident)+'-candidate-'+model_sha+'.json')
        if not report_path.exists():report_path=source.with_name((model_sample_id or ident)+'-neural-pilot.json')
        if report_path.exists():
            model_metadata=json.loads(report_path.read_text())
            if model_metadata.get('model_sha256')!=model_sha:raise ValueError('Encrypted candidate/report mismatch')
            context_frames=int(model_metadata.get('context_frames',75))
    warmup=max(25,(context_frames+2)//3)
    evidence_path=model.parent/'stream-report.json'
    evidence=json.loads(evidence_path.read_text()) if evidence_path.exists() and not encrypted_model else {}
    if evidence and evidence.get('sha256')!=model_sha:raise ValueError('Model/report mismatch')
    if not encrypted_model and (model.parent/'model.json').exists():
        model_metadata=json.loads((model.parent/'model.json').read_text())
        if model_metadata.get('sha256')!=model_sha:raise ValueError('Public model metadata mismatch')
        context_frames=int(model_metadata.get('context_frames',75));warmup=max(25,(context_frames+2)//3)
        evidence={**model_metadata,**evidence}
    cutoff=int(evidence.get('cutoff',250));window=int(evidence.get('window',3))
    if window not in (3,10) or not 1<=cutoff<=255:raise ValueError('Unsupported inference policy')
    raw=bytearray(_dpapi(p.read_bytes(),decrypt=True))
    try:
        with wave.open(io.BytesIO(raw),'rb') as wav:
            assert (wav.getframerate(),wav.getnchannels(),wav.getsampwidth())==(16000,1,2)
            samples=np.frombuffer(wav.readframes(wav.getnframes()),dtype='<i2').copy()
        assert len(samples)<=16000*60
        front=MicroFrontend();rows=[]
        for offset in range(0,len(samples)-159,160):
            r=front.process_samples(samples[offset:offset+160].tobytes())
            assert r.samples_read==160
            if r.features:rows.append(r.features)
        runtime=Interpreter(model_content=model_bytes,experimental_op_resolver_type=OpResolverType.BUILTIN_WITHOUT_DEFAULT_DELEGATES)
        runtime.allocate_tensors();inp=runtime.get_input_details()[0];out=runtime.get_output_details()[0]
        assert inp['shape'].tolist()==[1,3,40]
        assert inp['dtype']==np.int8 and out['dtype']==np.uint8
        assert inp['quantization'][1]==-128 and np.isclose(inp['quantization'][0],26/255,atol=1e-6)
        scale,zero=inp['quantization'];q=np.clip(np.rint(np.array(rows)/scale)+zero,-128,127).astype(np.int8)
        probabilities=[]
        for i in range(0,len(q)-2,3):
            runtime.set_tensor(inp['index'],q[None,i:i+3]);runtime.invoke()
            probabilities.append(int(runtime.get_tensor(out['index'])[0,0]))
        scores=np.convolve(probabilities,np.ones(window)/window,mode='full')[:len(probabilities)]
        events=[]
        for i in np.flatnonzero(scores>=cutoff):
            if i>=warmup-1 and (not events or i-events[-1]>=50):events.append(int(i))
        windows=samples[:len(samples)//320*320].reshape(-1,320).astype(np.float64)
        rms=np.sqrt(np.mean(windows**2,axis=1));threshold=max(100,float(np.percentile(rms,15))*3)
        active=np.flatnonzero(rms>=threshold);segments=[]
        for frame in active:
            if not segments or frame-segments[-1][1]>20:segments.append([int(frame),int(frame)])
            else:segments[-1][1]=int(frame)
        domain=metadata.get('capture_domain','post_afe_opus')
        report={'seconds':len(samples)/16000,'local_only':True,'frontend_parity':1987024791,
            'capture_domain':domain,'device_kws_input_equivalent':domain=='mono_pcm16_pre_afe',
            'context_frames':context_frames,'warmup_invocations':warmup,'probability_window':window,
            'event_seconds':[round(i*.03+.05,2) for i in events],
            'speech_segment_seconds':[[round(a*.02,2),round((b+1)*.02,2)] for a,b in segments if b-a>=8],
            'peak_score':max(probabilities,default=0),'cutoff':cutoff,'model_sha256':model_sha,
            'clipped_fraction':float(np.mean(np.abs(samples.astype(np.int32))>=32760)),
            'rms_quantiles':np.percentile(rms,[10,50,90]).round(2).tolist(),
            'human_labels_verified':False,'true_positive_count':None,'false_positive_count':None}
        (p.parent/(ident+'-'+model_sha[:12]+'-evaluation.json')).write_text(json.dumps(report,indent=2))
        print(json.dumps(report))
    finally:
        raw[:]=bytes(len(raw))
        if 'samples' in locals():samples.fill(0)
        if 'q' in locals():q.fill(0)

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('sample_id');a.add_argument('--model',type=Path,default=Path(__file__).with_name('gobot.tflite'));a.add_argument('--encrypted-personal-model',action='store_true');a.add_argument('--personal-model-sample');v=a.parse_args();evaluate(v.sample_id,v.model,v.encrypted_personal_model or bool(v.personal_model_sample),v.personal_model_sample)
