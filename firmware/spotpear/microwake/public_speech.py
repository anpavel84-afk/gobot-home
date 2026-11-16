"""Bounded CC-BY-4.0 public background speech, recomputed at native10ms.

Downloads one337MB OpenSLR archive, verifies its published checksum. Never
extracts archive paths to disk, reads household audio or calls a provider API.
"""
import argparse,hashlib,io,json,re,subprocess,tarfile,time,urllib.request
from pathlib import Path,PurePosixPath
import numpy as np
from train_reference import features

URL='https://openslr.trmal.net/resources/12/dev-clean.tar.gz'
MD5='42e2234ba48799c1f50f24a7926300a1'
LICENSE='CC-BY-4.0'


def permitted_text(text):
    return not re.search(r'\b(?:GO\s*BOT|GA\s*BOT|GOBOT|GABOT)\b',text.upper())


def main(root):
    root=root.resolve();root.mkdir();started=time.monotonic();archive=root/'dev-clean.tar.gz';size=0;md5=hashlib.md5()
    with urllib.request.urlopen(URL,timeout=45) as response,archive.with_suffix('.part').open('xb') as output:
        while chunk:=response.read(1024*1024):
            size+=len(chunk)
            if size>400*1024**2 or time.monotonic()-started>900:raise RuntimeError('Public download size/time cap')
            output.write(chunk);md5.update(chunk)
    if md5.hexdigest()!=MD5:raise ValueError('OpenSLR published archive checksum mismatch')
    archive.with_suffix('.part').replace(archive);rng=np.random.default_rng(20261122)
    with tarfile.open(archive,'r:gz') as tar:
        texts={};groups={}
        for member in tar.getmembers():
            path=PurePosixPath(member.name)
            if path.is_absolute() or '..' in path.parts or member.issym() or member.islnk():raise ValueError('Unsafe archive structure')
            if member.isfile() and member.name.endswith('.trans.txt'):
                if member.size>1024**2:raise ValueError('Oversized public transcript')
                for line in tar.extractfile(member).read().decode().splitlines():
                    ident,_,text=line.partition(' ')
                    if permitted_text(text):texts[ident]=text
            if member.isfile() and member.name.endswith('.flac'):
                if len(path.parts)!=5 or path.parts[:2]!=('LibriSpeech','dev-clean') or not re.fullmatch(r'\d+-\d+-\d+\.flac',path.name) or member.size>4*1024**2:raise ValueError('Unexpected public audio member')
                groups.setdefault(path.parts[2],[]).append(member)
        speakers=sorted(groups);rng.shuffle(speakers)
        if len(speakers)!=40:raise ValueError('Unexpected OpenSLR speaker inventory')
        manifest=[]
        for index,speaker in enumerate(speakers):
            split='training' if index<32 else 'validation';folder=root/split;folder.mkdir(exist_ok=True);members=groups[speaker];rng.shuffle(members);kept=0
            for member in members:
                ident=PurePosixPath(member.name).stem
                if ident not in texts:continue
                if time.monotonic()-started>2400:raise RuntimeError('Public corpus preparation time cap')
                decoded=subprocess.run(['/usr/bin/ffmpeg','-v','error','-threads','1','-i','pipe:0','-t','36','-f','s16le','-ac','1','-ar','16000','pipe:1'],input=tar.extractfile(member).read(),capture_output=True,check=True,timeout=20).stdout
                samples=len(decoded)//2
                if not 3*16000<=samples<=35*16000:continue
                name='negative-'+ident+'.pcm';(folder/name).write_bytes(decoded)
                manifest.append({'file':split+'/'+name,'speaker':speaker,'split':split,'label':'negative','public_recorded_speech':True,'sha256':hashlib.sha256(decoded).hexdigest(),'samples':samples,'transcript_sha256':hashlib.sha256(texts[ident].encode()).hexdigest()});kept+=1
                if kept==25:break
            if kept<10:raise ValueError('Insufficient public voice coverage')
            print(json.dumps({'public_voice_complete':index+1,'voices':40,'split':split,'clips':kept}),flush=True)
    (root/'manifest.json').write_text(json.dumps(manifest,indent=2))
    (root/'SOURCE.md').write_text('LibriSpeech ASR corpus, OpenSLR SLR12. Vassil Panayotov, Guoguo Chen, Daniel Povey and Sanjeev Khudanpur. CC BY 4.0. https://www.openslr.org/12/\nSource audio decoded/resampled to mono PCM16k; feature hop10ms. ASR dev-clean repurposed for our keyword training with independent32/8 speaker split. No household speech.\n')
    (root/'provenance.json').write_text(json.dumps({'schema':'gobot-librispeech-negative-v1','source_url':URL,'source_md5':MD5,'license':LICENSE,'owner_audio':False,'public_recorded_speech':True,'training_speakers':speakers[:32],'validation_speakers':speakers[32:],'seed':20261122,'archive_bytes':size,'paid_calls':0}))
    for split in ('training','validation'):
        windows=[]
        for row in manifest:
            if row['split']!=split:continue
            path=root/row['file'];raw=path.read_bytes()
            if hashlib.sha256(raw).hexdigest()!=row['sha256']:raise ValueError('Changed public speech')
            pcm=np.frombuffer(raw,'<i2').astype(float);wave=np.clip(np.concatenate([rng.normal(0,20,40000),pcm*rng.uniform(.5,1.5),np.zeros(16000)]),-32768,32767).astype('<i2');rows=features(wave)
            for end in range(250,len(rows)+1,68):windows.append(rows[end-204:end].astype(np.float16))
        count=min(len(windows),20000 if split=='training' else 5000)
        if count<1000:raise ValueError('Insufficient native public speech features')
        selected=rng.choice(len(windows),count,replace=False);out=root/(split+'.npy');np.save(out,np.asarray([windows[i] for i in selected],np.float16))
        out.with_suffix('.json').write_text(json.dumps({'schema':'licensed-public-speech-native-v1','license':LICENSE,'source_url':URL,'source_md5':MD5,'owner_audio':False,'split':split,'speakers':speakers[:32] if split=='training' else speakers[32:],'excluded_speakers':speakers[32:] if split=='training' else speakers[:32],'frontend_hop_samples':160,'context_frames':204,'windows':count,'sha256':hashlib.sha256(out.read_bytes()).hexdigest(),'paid_calls':0}))
        print(json.dumps({'public_features':split,'windows':count,'native_hop_ms':10}),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('isolated_output',type=Path);a=p.parse_args();main(a.isolated_output)
