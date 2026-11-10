"""Local-only SpeechBrain embedding worker. Private stdio, no network/listener/auth."""
import base64,contextlib,io,json,os,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
os.environ['HF_HUB_OFFLINE']='1'
os.environ['HF_HOME']=str(ROOT/'run/speaker-hf')
os.environ['HF_HUB_DISABLE_TELEMETRY']='1'
model=None
def embed(pcm):
    global model
    with contextlib.redirect_stdout(sys.stderr):
        import numpy as np
        import torch
        from speechbrain.inference.classifiers import EncoderClassifier
        from speechbrain.utils.fetching import FetchConfig,LocalStrategy
        torch.set_num_threads(2)
        if model is None:
            location=ROOT/'data/models/ecapa'
            model=EncoderClassifier.from_hparams(source=str(location),savedir=str(ROOT/'run/speaker-cache'),
                overrides={'pretrained_path':str(location)},run_opts={'device':'cpu'},
                local_strategy=LocalStrategy.COPY,fetch_config=FetchConfig(allow_network=False,token=False))
        signal=torch.from_numpy(np.frombuffer(pcm,dtype='<i2').astype(np.float32)/32768).unsqueeze(0)
        with torch.inference_mode():return model.encode_batch(signal).reshape(-1).tolist()
for raw in sys.stdin.buffer:
    try:
        if len(raw)>4000000:raise ValueError('request limit')
        item=json.loads(raw);pcm=base64.b64decode(item['pcm'],validate=True)
        if len(pcm)>1920000 or len(pcm)%2:raise ValueError('invalid pcm')
        started=time.perf_counter();vector=embed(pcm)
        result={'id':item['id'],'embedding':vector,'embedding_ms':(time.perf_counter()-started)*1000}
    except Exception:
        result={'error':'speaker_embedding_unavailable'}
    print(json.dumps(result),flush=True)
