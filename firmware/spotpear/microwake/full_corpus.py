"""Full-scale extension of the existing offline Russian TTS corpus.

50,000 generated positive PCM clips, 10,000 adversarial negative PCM clips.
Not a count of augmented feature windows. Uses only existing pinned voice tools;
no network, private recordings, provider API or global installation.
"""
import argparse,hashlib,io,json,os,shutil,subprocess,tempfile,time,wave
from pathlib import Path
import numpy as np
from expanded_corpus import SPEAKERS,phrases,HASHES,pcm16,VARIANTS

SEED=20261115
COUNTS={'positive':10000,'negative':2000}


def normalize_clip(pcm,label):
    """Preserve short, audible negative phonemes; never invent positive speech."""
    if not 1600<=len(pcm)<=320000 or int(np.max(np.abs(pcm.astype(np.int32))))<32:
        raise ValueError('Invalid generated speech')
    if len(pcm)<3200:
        if label!='negative':raise ValueError('Positive speech too short')
        pcm=np.pad(pcm,(0,3200-len(pcm)))
    return pcm


def plan(speaker):
    if speaker not in SPEAKERS:raise ValueError('Unreviewed TRAIN voice')
    rng=np.random.default_rng(SEED+SPEAKERS.index(speaker)*17)
    positives=[v['text'].rstrip('.!?')+punct for v in VARIANTS for punct in ('.','!','?')]
    _,negative=phrases();negative=list(dict.fromkeys(negative+['Го','Гоу','Бо','Гоб','Обод','Гоголь','Говори','Колобок']))
    result=[]
    for label,texts in [('positive',positives),('negative',negative)]:
        used=set()
        for index in range(COUNTS[label]):
            for attempt in range(100):
                text=texts[int(rng.integers(len(texts)))];speed=int(rng.integers(70,131));pitch=int(rng.integers(-20,21))
                key=(text,speed,pitch)
                if key not in used:break
            else:raise ValueError('Prosody inventory exhausted')
            used.add(key)
            result.append({'file':f'{label}-full-{index:05}.pcm','text':text,'speaker':speaker,'label':label,'synthetic':True,
                'speed':speed,'pitch':pitch,'noise_scale':round(float(rng.uniform(.35,1.)),6),'noise_w_scale':round(float(rng.uniform(.5,1.2)),6)})
    return result


def voice_for(stage,speaker):
    import onnxruntime
    from piper import PiperVoice
    from piper.config import PiperConfig
    voice=None
    if speaker in HASHES:
        files=[stage/'voices'/f'ru_RU-{speaker}-medium.{ext}' for ext in ('onnx','onnx.json')]
        for path,digest in zip(files,HASHES[speaker]):
            if hashlib.sha256(path.read_bytes()).hexdigest()!=digest:raise ValueError('Existing Piper voice changed')
        options=onnxruntime.SessionOptions();options.intra_op_num_threads=2;options.inter_op_num_threads=1;options.log_severity_level=3
        voice=PiperVoice(session=onnxruntime.InferenceSession(str(files[0]),sess_options=options,providers=['CPUExecutionProvider']),config=PiperConfig.from_dict(json.loads(files[1].read_text())))
    return voice


def synthesize(task,voice,stage,out):
    from piper import SynthesisConfig
    speaker=task['speaker'];rh=stage/'rh-local/root';es=stage/'espeak-local/root'
    environment=dict(os.environ,LD_LIBRARY_PATH=f'{rh}/usr/lib/x86_64-linux-gnu:{es}/usr/lib/x86_64-linux-gnu',RHVOICE_DATA_PATH=str(rh/'usr/share/RHVoice'),RHVOICE_CONFIG_PATH=str(stage/'reference-home'),ESPEAK_DATA_PATH=str(es/'usr/lib/x86_64-linux-gnu'))
    speed=task['speed'];pitch=task['pitch'];text=task['text']
    if voice:
        chunks=voice.synthesize(text,SynthesisConfig(length_scale=speed/100,noise_scale=task['noise_scale'],noise_w_scale=task['noise_w_scale']))
        pcm=pcm16(np.concatenate([c.audio_float_array for c in chunks])*32767,voice.config.sample_rate)
        ratio=2**(pitch/60)
        pcm=np.clip(np.interp(np.arange(0,len(pcm),ratio),np.arange(len(pcm)),pcm.astype(float)),-32768,32767).astype('<i2')
    elif speaker=='espeak-ru':
        result=subprocess.run([str(es/'usr/bin/espeak-ng'),'-v','ru','-p',str(50+pitch),'-s',str(round(16500/speed)),'--stdout',text],env=environment,check=True,capture_output=True,timeout=15)
        with wave.open(io.BytesIO(result.stdout)) as wav:pcm=pcm16(np.frombuffer(wav.readframes(wav.getnframes()),'<i2').astype(float),wav.getframerate())
    else:
        with tempfile.TemporaryDirectory(dir=out) as temp:
            wav_path=Path(temp)/'clip.wav'
            subprocess.run([str(rh/'usr/bin/RHVoice-test'),'-p',speaker.title(),'-r',str(100-speed),'-t',str(pitch),'-o',str(wav_path)],input=text.encode(),env=environment,check=True,capture_output=True,timeout=15)
            with wave.open(str(wav_path)) as wav:pcm=pcm16(np.frombuffer(wav.readframes(wav.getnframes()),'<i2').astype(float),wav.getframerate())
    pcm=normalize_clip(pcm,task['label'])
    return pcm


def main(stage,out):
    import fcntl,onnxruntime
    from piper import PiperVoice,SynthesisConfig
    from piper.config import PiperConfig
    stage=stage.resolve();out=out.resolve()
    if not out.is_relative_to(stage) or out==stage:raise ValueError('Use an isolated public-corpus child of the existing stage')
    out.mkdir(parents=True,exist_ok=True)
    lock=(out/'generation.lock').open('a');fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    provenance={'schema':'gobot-full-tts-v1','seed':SEED,'speakers':list(SPEAKERS),'synthetic_only':True,
        'positive_per_voice':10000,'negative_per_voice':2000,'positive_total':50000,'negative_total':10000,
        'source_waveform_clips_not_feature_windows':True,'network':False,'paid_calls':0,
        'onnx_intra_threads':2,'onnx_inter_threads':1,'resume_preserves_existing_audio':True,
        'bitwise_tts_regeneration_after_resume_guaranteed':False,
        'piper_pitch_transform':'resample ratio 2**(pitch/60), bounded +/-4 semitones'}
    p=out/'provenance.json'
    if p.exists() and json.loads(p.read_text())!=provenance:raise ValueError('Existing corpus scope differs; no overwrite')
    p.write_text(json.dumps(provenance,indent=2))
    (out/'quality-adjustment.json').write_text(json.dumps({'revision':2,'audible_negative_min_samples':1600,'short_negative_zero_padding_to_samples':3200,'positive_min_samples':3200,'unchanged_existing_audio':True}))
    rh=stage/'rh-local/root';es=stage/'espeak-local/root'
    license_path=rh/'usr/share/doc/rhvoice-russian/copyright';license_text=license_path.read_text()
    if 'License: LGPL-2.1+' not in license_text or 'Files: data/voices/irina/*' in license_text:raise ValueError('Re-review changed existing RHVoice inventory')
    shutil.copy2(license_path,out/'rhvoice-copyright.txt')
    environment=dict(os.environ,LD_LIBRARY_PATH=f'{rh}/usr/lib/x86_64-linux-gnu:{es}/usr/lib/x86_64-linux-gnu',
        RHVOICE_DATA_PATH=str(rh/'usr/share/RHVoice'),RHVOICE_CONFIG_PATH=str(stage/'reference-home'),ESPEAK_DATA_PATH=str(es/'usr/lib/x86_64-linux-gnu'))
    started=time.monotonic();written_bytes=0;completed=0;onnxruntime.set_seed(SEED)
    for speaker in SPEAKERS:
        folder=out/speaker;folder.mkdir(exist_ok=True);tasks=plan(speaker);by_name={t['file']:t for t in tasks}
        plan_sha=hashlib.sha256(json.dumps(tasks,sort_keys=True).encode()).hexdigest()
        state_path=folder/'plan.json'
        if state_path.exists() and json.loads(state_path.read_text())['sha256']!=plan_sha:raise ValueError('Plan changed during resume')
        state_path.write_text(json.dumps({'sha256':plan_sha,'clips':len(tasks)}))
        journal=folder/'manifest.jsonl';done={}
        if journal.exists():
            for line in journal.read_text().splitlines():
                item=json.loads(line);name=item['file']
                if name not in by_name or name in done or any(item.get(k)!=v for k,v in by_name[name].items()):raise ValueError('Invalid resume journal')
                data=(folder/name).read_bytes()
                if hashlib.sha256(data).hexdigest()!=item['sha256']:raise ValueError('Existing clip changed')
                done[name]=item;written_bytes+=len(data);completed+=1
        voice=voice_for(stage,speaker)
        with journal.open('a') as stream:
            for task in tasks:
                if task['file'] in done:continue
                if time.monotonic()-started>21600 or written_bytes>12*1024**3 or shutil.disk_usage(out).free<1024**3:raise RuntimeError('Bounded generation time/disk limit reached; preserve partial corpus')
                target=folder/task['file']
                if target.exists():raise ValueError('Unjournaled completed clip needs operator review; do not overwrite')
                pcm=synthesize(task,voice,stage,out)
                raw=pcm.tobytes();temp=target.with_suffix('.part')
                if temp.exists():raise ValueError('Unfinished temporary clip needs review')
                with temp.open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
                temp.replace(target)
                item={**task,'sha256':hashlib.sha256(raw).hexdigest(),'samples':len(pcm)}
                stream.write(json.dumps(item,ensure_ascii=False)+'\n');stream.flush();done[task['file']]=item
                completed+=1;written_bytes+=len(raw)
                if completed%100==0:
                    os.fsync(stream.fileno())
                    progress={'completed':completed,'total':60000,'bytes':written_bytes,'elapsed_seconds':round(time.monotonic()-started,1),'speaker':speaker,'paid_calls':0}
                    temp=out/'progress.tmp';temp.write_text(json.dumps(progress));temp.replace(out/'progress.json');print(json.dumps(progress),flush=True)
        manifest=[done[t['file']] for t in tasks]
        (folder/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False),encoding='utf-8')
        print(json.dumps({'speaker_complete':speaker,'clips':len(manifest),'unique_audio_hashes':len({i['sha256'] for i in manifest})}),flush=True)
    (out/'complete.json').write_text(json.dumps({'clips':completed,'bytes':written_bytes,'paid_calls':0,'ready_for_feature_extraction':completed==60000}))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('existing_stage',type=Path);p.add_argument('output',type=Path)
    a=p.parse_args();main(a.existing_stage,a.output)
