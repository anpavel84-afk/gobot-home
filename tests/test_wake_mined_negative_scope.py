import importlib.util,json,hashlib,time
from pathlib import Path
import pytest

f=Path(__file__).resolve().parents[1]/'firmware/spotpear/microwake/original_replay.py'
s=importlib.util.spec_from_file_location('mined_replay_scope',f);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)


def fixture(tmp_path):
    ident='a'*32;root=tmp_path/'public';train=['denis','dmitri','espeak-ru','anna','irina'];hashes={}
    for speaker in train:
        d=root/speaker;d.mkdir(parents=True);p=d/'manifest.json';p.write_text('[]');hashes[speaker]=hashlib.sha256(p.read_bytes()).hexdigest()
    negatives=[]
    for i in range(32):
        p=root/'denis'/f'negative-{i}.pcm';p.write_bytes(b'public');negatives.append(p)
    data={'kind':'private_teacher_public_train_negatives','synthetic_only':True,'source_sample':ident,
        'expires_at':time.time()+100,'training_speakers':train,'excluded_speakers':['aleksandr','elena'],
        'kernel_baseline':'native_reference','corpus_manifest_sha256':hashes,
        'clips':[{'file':p.relative_to(root).as_posix()} for p in negatives]}
    path=tmp_path/(ident+'-mined-public-negatives.json');path.write_text(json.dumps(data))
    return root,path,ident,negatives,data


def test_only_verified_train_negatives_are_replayed(tmp_path):
    root,path,ident,neg,data=fixture(tmp_path)
    assert m.mined_negatives(root,path,ident,time.time()+200,neg)==neg


@pytest.mark.parametrize('failure',['heldout','traversal','expiry','foreign_sample','changed_corpus','duplicate'])
def test_unsafe_or_stale_selections_refused(tmp_path,failure):
    root,path,ident,neg,data=fixture(tmp_path)
    if failure=='heldout':data['clips'][0]['file']='elena/negative-0.pcm'
    elif failure=='traversal':data['clips'][0]['file']='../private.wav'
    elif failure=='expiry':data['expires_at']=time.time()-1
    elif failure=='foreign_sample':data['source_sample']='b'*32
    elif failure=='changed_corpus':(root/'denis/manifest.json').write_text('changed')
    else:data['clips'][1]=data['clips'][0]
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):m.mined_negatives(root,path,ident,time.time()+200,neg)
