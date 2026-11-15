import hashlib,importlib.util,json
from pathlib import Path
import pytest
import shutil
FILE=Path(__file__).resolve().parents[1]/'firmware/spotpear/microwake/original_replay.py'
spec=importlib.util.spec_from_file_location('original_wake_replay',FILE);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

@pytest.fixture
def corpus(tmp_path):
    for speaker in m.SPEAKERS:
        folder=tmp_path/speaker;folder.mkdir();entries=[]
        for label,count in [('positive',15),('negative',198)]:
            for i in range(count):
                name=f'{label}-{i}.pcm';data=i.to_bytes(2,'little');(folder/name).write_bytes(data)
                entries.append({'file':name,'label':label,'speaker':speaker,'synthetic':True,'sha256':hashlib.sha256(data).hexdigest(),'text':'Русская речь'})
        (folder/'manifest.json').write_text(json.dumps(entries,ensure_ascii=False),encoding='utf-8')
    return tmp_path

def test_only_original_speakers_and_all_hashes(corpus):
    (corpus/'dmitri').mkdir();(corpus/'elena').mkdir()
    pos,neg=m.corpus(corpus);assert len(pos)==60 and len(neg)==792
    assert all(p.parent.name in m.SPEAKERS for p in pos+neg)

def test_tampered_pcm_rejected(corpus):
    (corpus/'denis/negative-0.pcm').write_bytes(b'changed')
    with pytest.raises(ValueError,match='hash'):m.corpus(corpus)

def test_reference_split_excludes_aleksandr_and_elena(corpus):
    shutil.copytree(corpus/'denis',corpus/'dmitri')
    path=corpus/'dmitri/manifest.json';entries=json.loads(path.read_text(encoding='utf-8'))
    for item in entries:item['speaker']='dmitri'
    path.write_text(json.dumps(entries))
    positive,negative=m.corpus(corpus,('denis','dmitri','espeak-ru','anna'))
    assert len(positive)==60 and len(negative)==792
    assert not any(path.parent.name in ('aleksandr','elena') for path in positive+negative)
    with pytest.raises(ValueError,match='Unreviewed'):m.corpus(corpus,('denis','elena'))

@pytest.mark.parametrize('mutation',['speaker','missing'])
def test_manifest_leak_or_incomplete_original_rejected(corpus,mutation):
    p=corpus/'denis/manifest.json';entries=json.loads(p.read_text(encoding='utf-8'))
    if mutation=='speaker':entries[0]['speaker']='elena'
    else:entries.pop()
    p.write_text(json.dumps(entries),encoding='utf-8')
    with pytest.raises(ValueError):m.corpus(corpus)
