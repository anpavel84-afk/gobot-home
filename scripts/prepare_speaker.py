"""Pin public ECAPA artifacts; never use account tokens or remote custom Python."""
import hashlib,json,sys
from pathlib import Path
import urllib.request
ROOT=Path(__file__).resolve().parents[1]
REVISION='0f99f2d0ebe89ac095bcc5903c4dd8f72b367286'
FILES=['hyperparams.yaml','embedding_model.ckpt','mean_var_norm_emb.ckpt','classifier.ckpt','label_encoder.txt','README.md','example1.wav','example2.flac']
def main():
    target=ROOT/'data/models/ecapa';target.mkdir(parents=True,exist_ok=True)
    metadata=json.load(urllib.request.urlopen('https://huggingface.co/api/models/speechbrain/spkrec-ecapa-voxceleb/revision/'+REVISION+'?blobs=true',timeout=30))
    result={'repo':'speechbrain/spkrec-ecapa-voxceleb','revision':REVISION,'model_license':'Apache-2.0','files':[]}
    for name in FILES:
        info=next(x for x in metadata['siblings'] if x['rfilename']==name);path=target/name
        expected=info.get('lfs',{}).get('sha256')
        if not path.exists() or expected and hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
            temporary=path.with_suffix(path.suffix+'.part')
            with urllib.request.urlopen('https://huggingface.co/speechbrain/spkrec-ecapa-voxceleb/resolve/'+REVISION+'/'+name,timeout=60) as source,temporary.open('wb') as out:
                while chunk:=source.read(1048576):out.write(chunk)
            if expected and hashlib.sha256(temporary.read_bytes()).hexdigest()!=expected:raise RuntimeError('model checksum mismatch')
            temporary.replace(path)
        result['files'].append({'name':name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
        print('Verified public speaker artifact:',name,flush=True)
    (ROOT/'docs/speaker-model.lock.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
if __name__=='__main__':main()
