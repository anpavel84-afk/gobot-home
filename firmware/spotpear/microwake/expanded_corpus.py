"""Bounded, offline TTS corpus: Russian name plus immediate question and confusables.

Uses already installed project-local tools/voice files; no network, recordings,
paid APIs, global installs or overwriting earlier corpora. Irina here is RHVoice,
not the unrelated Piper model with an unreviewed model card.
"""
import argparse,hashlib,io,json,os,shutil,subprocess,tempfile,wave
from pathlib import Path
import numpy as np
import onnxruntime
from piper import PiperVoice,SynthesisConfig
from piper.config import PiperConfig
from corpus import NEGATIVE,HASHES,pcm16
from wake_variants import VARIANTS

SPEAKERS=('denis','dmitri','espeak-ru','anna','irina')
QUESTIONS=('',' Какая погода завтра?',' Поставь таймер.',' Который час?',' Расскажи про Луну.')
SENTENCES=(
    'Сегодня за окном идёт дождь','Завтра будет солнечно','Ребёнок читает книгу','На кухне стоит чайник',
    'Робот помогает по дому','Я готов начать работу','Погода снова изменилась','Какой бот отвечает на вопрос',
    'Мы собираемся в поход','Проверь календарь на завтра','Поставь таймер на пять минут','Отмени предыдущий таймер',
    'Подожди пожалуйста','Спасибо больше ничего не нужно','По дороге едет автобус','В огороде выросли помидоры',
    'Сколько сейчас времени','Кто сегодня придёт в гости','Открой окно в комнате','На улице холодно и ветрено',
)


def phrases():
    negative=list(dict.fromkeys([*NEGATIVE,*SENTENCES,*[f'{prefix}, {text.lower()}' for prefix in ('Слушай','Хорошо','А теперь','Пожалуйста') for text in SENTENCES]]))
    if any('гобот' in text.lower().replace('́','') or 'gobot' in text.lower() for text in negative):raise ValueError('Wake word in negative text')
    positive=[variant['text'] if not question else variant['text'].rstrip('.!?')+','+question for variant in VARIANTS for question in QUESTIONS]
    return positive,negative


def main(stage,output,evaluation_only=False,reuse_negatives=None):
    if output.exists():raise ValueError('New corpus directory required')
    output.mkdir(parents=True)
    rh=stage/'rh-local/root';es=stage/'espeak-local/root'
    environment=dict(os.environ,LD_LIBRARY_PATH=f'{rh}/usr/lib/x86_64-linux-gnu:{es}/usr/lib/x86_64-linux-gnu',
        RHVOICE_DATA_PATH=str(rh/'usr/share/RHVoice'),RHVOICE_CONFIG_PATH=str(stage/'reference-home'),
        ESPEAK_DATA_PATH=str(es/'usr/lib/x86_64-linux-gnu'))
    # Exact Debian source-package inventory: generic data LGPL-2.1+, separate
    # NC/ND voices explicitly excluded. Existing Anna and new RHVoice Irina use
    # the generic stanza; keep its text/hash as provenance, no legal assertion.
    license_path=rh/'usr/share/doc/rhvoice-russian/copyright'
    license_text=license_path.read_text()
    if 'License: LGPL-2.1+' not in license_text or 'Files: data/voices/irina/*' in license_text:raise ValueError('Re-review changed RHVoice inventory')
    (output/'rhvoice-copyright.txt').write_text(license_text)
    speakers=('aleksandr','elena') if evaluation_only else SPEAKERS
    config={'synthetic_only':True,'speakers':speakers,'evaluation_only':evaluation_only,'validation_speakers':['aleksandr'],'test_speakers':['elena'],
        'positive_prefix_limit_samples':28800,'sample_rate':16000,'network':False,'paid_calls':0,'onnx_intra_threads':2,'onnx_inter_threads':1,
        'wake_variants_source':'wake_variants.VARIANTS','reused_negative_corpus':reuse_negatives.name if reuse_negatives else None,
        'rhvoice_copyright_sha256':hashlib.sha256(license_path.read_bytes()).hexdigest()}
    (output/'provenance.json').write_text(json.dumps(config,indent=2))
    positive,negative=phrases();onnxruntime.set_seed(1042)
    for speaker in speakers:
        folder=output/speaker;folder.mkdir();manifest=[]
        voice=None
        if speaker in HASHES:
            files=[stage/'voices'/f'ru_RU-{speaker}-medium.{extension}' for extension in ('onnx','onnx.json')]
            for path,digest in zip(files,HASHES[speaker]):
                if hashlib.sha256(path.read_bytes()).hexdigest()!=digest:raise ValueError('Piper voice hash mismatch')
            options=onnxruntime.SessionOptions();options.intra_op_num_threads=2;options.inter_op_num_threads=1
            options.log_severity_level=3
            voice=PiperVoice(session=onnxruntime.InferenceSession(str(files[0]),sess_options=options,providers=['CPUExecutionProvider']),
                config=PiperConfig.from_dict(json.loads(files[1].read_text())))
        for label,texts in [('positive',positive),('negative',negative)]:
            if label=='negative' and reuse_negatives:
                entries=json.loads((reuse_negatives/speaker/'manifest.json').read_text(encoding='utf-8'))
                selected=[item for item in entries if item['label']=='negative']
                if len(selected)!=len(negative)*3:raise ValueError('Incomplete reusable negative class')
                for item in selected:
                    name=item['file'];source=reuse_negatives/speaker/name
                    if Path(name).name!=name or source.is_symlink() or item['speaker']!=speaker or item['synthetic'] is not True or hashlib.sha256(source.read_bytes()).hexdigest()!=item['sha256']:raise ValueError('Reusable negative manifest mismatch')
                    shutil.copy2(source,folder/name);manifest.append(item)
                print(json.dumps({'speaker':speaker,'completed_class':'verified_negative_reuse','clips':len(manifest)}),flush=True)
                continue
            for index,text in enumerate(texts):
                for variant,speed in enumerate((85,100,115)):
                    if voice:
                        chunks=voice.synthesize(text,SynthesisConfig(length_scale=speed/100,noise_scale=.5+variant*.15,noise_w_scale=.6+variant*.1))
                        pcm=pcm16(np.concatenate([chunk.audio_float_array for chunk in chunks])*32767,voice.config.sample_rate)
                    elif speaker=='espeak-ru':
                        result=subprocess.run([str(es/'usr/bin/espeak-ng'),'-v','ru','-s',str(round(16500/speed)),'--stdout',text],env=environment,check=True,capture_output=True,timeout=15)
                        with wave.open(io.BytesIO(result.stdout)) as wav:pcm=pcm16(np.frombuffer(wav.readframes(wav.getnframes()),'<i2').astype(float),wav.getframerate())
                    else:
                        with tempfile.TemporaryDirectory(dir=output) as temporary:
                            wav_path=Path(temporary)/'clip.wav'
                            subprocess.run([str(rh/'usr/bin/RHVoice-test'),'-p',speaker.title(),'-r',str(100-speed),'-t',str((variant-1)*8),'-o',str(wav_path)],
                                input=text.encode(),env=environment,check=True,capture_output=True,timeout=15)
                            with wave.open(str(wav_path)) as wav:pcm=pcm16(np.frombuffer(wav.readframes(wav.getnframes()),'<i2').astype(float),wav.getframerate())
                    if label=='positive':pcm=pcm[:28800] # Retain beginning/name; only following question tail may be cut.
                    if not len(pcm) or len(pcm)>16000*20:raise ValueError('Invalid generated clip duration')
                    name=f'{label}-{index}-{speed}.pcm';pcm.tofile(folder/name)
                    manifest.append({'file':name,'text':text,'label':label,'speaker':speaker,'synthetic':True,'sha256':hashlib.sha256(pcm.tobytes()).hexdigest()})
            print(json.dumps({'speaker':speaker,'completed_class':label,'clips':len(manifest)}),flush=True)
        (folder/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',type=Path);p.add_argument('output',type=Path);p.add_argument('--evaluation-only',action='store_true');p.add_argument('--both-splits',action='store_true');p.add_argument('--reuse-negatives',type=Path);a=p.parse_args()
    stage=a.stage.resolve();output=a.output.resolve();reuse=a.reuse_negatives.resolve() if a.reuse_negatives else None
    if a.both_splits:
        if a.evaluation_only or output.exists():raise ValueError('Both splits require a new parent directory')
        output.mkdir(parents=True);main(stage,output/'train',False,reuse);main(stage,output/'heldout',True,reuse)
    else:main(stage,output,a.evaluation_only,reuse)
