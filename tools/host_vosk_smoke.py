"""Explicit one-time public model setup and vocabulary smoke, never room capture.
Run in the isolated HOST venv. No automatic download from the runtime detector.
"""
import argparse,hashlib,json,os,socket,time,urllib.request,zipfile
from pathlib import Path
MODEL='vosk-model-small-ru-0.22'
URL='https://alphacephei.com/vosk/models/'+MODEL+'.zip'

def main(root):
    root=Path(root).resolve();root.mkdir(parents=True,exist_ok=True)
    archive=root/(MODEL+'.zip');model=root/MODEL
    if not archive.exists():
        tmp=archive.with_suffix('.part')
        assert not tmp.exists(), 'Review incomplete model download, no hidden retry'
        with urllib.request.urlopen(URL,timeout=30) as source,tmp.open('xb') as target:
            total=0
            while block:=source.read(1024*1024):
                total+=len(block)
                if total>70*1024**2:raise ValueError('model_download_limit')
                target.write(block)
        tmp.replace(archive)
    digest=hashlib.sha256(archive.read_bytes()).hexdigest()
    if not model.exists():
        with zipfile.ZipFile(archive) as z:
            assert sum(i.file_size for i in z.infolist())<300*1024**2
            for i in z.infolist():
                path=(root/i.filename).resolve()
                assert path.is_relative_to(root) and i.filename.startswith(MODEL+'/') and not (i.external_attr>>16)&0o170000==0o120000
            z.extractall(root)
    from vosk import Model,KaldiRecognizer,SetLogLevel
    SetLogLevel(-1)
    # Inference has no Python network access, unlike model acquisition above.
    def deny(*a,**kw):raise RuntimeError('network_forbidden_during_inference')
    socket.create_connection=deny
    started=time.perf_counter();m=Model(str(model));load_ms=(time.perf_counter()-started)*1000
    terms=['гобот','габот','гоп'];lookup={s:m.vosk_model_find_word(s) for s in terms}
    rec=KaldiRecognizer(m,16000);rec.SetWords(True);rec.SetPartialWords(True)
    started=time.perf_counter()
    for _ in range(500):rec.AcceptWaveform(bytes(1920));rec.PartialResult()
    elapsed=time.perf_counter()-started
    report={'model':MODEL,'source':URL,'license':'Apache-2.0 per official model catalog','archive_sha256':digest,'lookup_word_ids':lookup,'required_words_available':all(v>=0 for v in lookup.values()),'grammar_injected':False,'aliases_or_fuzzy_matching':False,'model_load_ms':round(load_ms,2),'silence_audio_seconds':30,'silence_compute_seconds':round(elapsed,3),'paid_calls':0,'microphone_opened':False,'phrase_smoke':'BLOCKED_OOV' if any(v<0 for v in lookup.values()) else 'NOT_RUN','human_accepted':False}
    (root/'vosk-smoke.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(report,ensure_ascii=True))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('model_root');main(p.parse_args().model_root)
