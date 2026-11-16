import importlib.util,json
from pathlib import Path
import pytest
FILE=Path(__file__).resolve().parents[1]/'firmware/spotpear/microwake/sample_retention.py'
spec=importlib.util.spec_from_file_location('wake_sample_retention',FILE);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)

@pytest.mark.parametrize('ident',['../outside','a'*31,'a'*33,'x'*32,'a'*32+'/file'])
def test_sample_path_rejects_arbitrary_files(ident):
    with pytest.raises(ValueError):mod.paths(ident)

def test_expiry_removes_only_the_one_sample(tmp_path,monkeypatch):
    monkeypatch.setattr(mod,'ROOT',tmp_path);monkeypatch.setattr(mod,'DIRECTORY',tmp_path/'samples');mod.DIRECTORY.mkdir()
    p,meta=mod.paths('a'*32);p.write_bytes(b'opaque-fixture');meta.write_text(json.dumps({'expires_at':200}))
    derived=p.with_name('a'*32+'-personal-model.dpapi');derived.write_bytes(b'derived-fixture')
    other=mod.DIRECTORY/'leave-alone';other.write_bytes(b'other')
    candidate=mod.candidate_path('a'*32,'b'*64);candidate.write_bytes(b'encrypted-candidate')
    other_candidate=mod.candidate_path('c'*32,'d'*64);other_candidate.write_bytes(b'other-owner')
    selection=p.with_name('a'*32+'-mined-public-negatives.json');selection.write_text('{}')
    export=mod.DIRECTORY/('a'*32+'-export-abcd1234');export.mkdir();(export/'private.weights').write_bytes(b'private-export')
    other_export=mod.DIRECTORY/('c'*32+'-export-abcd1234');other_export.mkdir()
    assert not mod.cleanup('a'*32,199) and p.exists()
    assert selection.exists()
    assert mod.cleanup('a'*32,201) and not p.exists() and not derived.exists() and other.exists()
    assert not candidate.exists() and other_candidate.exists()
    assert not selection.exists()
    assert not export.exists() and other_export.exists()
    assert json.loads(meta.read_text())['deleted'] is True

@pytest.mark.parametrize('sha',['../escape','b'*63,'B'*64])
def test_candidate_path_rejects_invalid_hash(sha):
    with pytest.raises(ValueError):mod.candidate_path('a'*32,sha)
