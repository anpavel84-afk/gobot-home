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
    other=mod.DIRECTORY/'leave-alone';other.write_bytes(b'other')
    assert not mod.cleanup('a'*32,199) and p.exists()
    assert mod.cleanup('a'*32,201) and not p.exists() and other.exists()
    assert json.loads(meta.read_text())['deleted'] is True
