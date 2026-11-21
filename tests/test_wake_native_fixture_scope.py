import hashlib,importlib.util,json,sys
from pathlib import Path
import pytest

HERE=Path(__file__).resolve().parents[1]/'firmware/spotpear/microwake'
sys.path.insert(0,str(HERE))
spec=importlib.util.spec_from_file_location('prepare_native_parity',HERE/'prepare_native_parity.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


def inputs(tmp_path):
    root=tmp_path/'copy';main=root/'main';main.mkdir(parents=True)
    (root/'CMakeLists.txt').write_text('0.4.9-dev-owner-wake-test-1')
    (main/'gobot_mww_config.h').write_text('#define GOBOT_WAKE_ROUTE 0\n#define GOBOT_WAKE_OWNER_TEST 1')
    fixture=tmp_path/'fixture';fixture.mkdir();header=fixture/'gobot_mww_fixture.h';header.write_text('public test fixture')
    meta={'synthetic_only':True,'model_sha256':'4ffc532e16b3e20b7ce09099338023b5af304a0e31bf537034bb03dd67a4c5f9',
        'header_sha256':hashlib.sha256(header.read_bytes()).hexdigest(),'invocations':10}
    (fixture/'fixture.json').write_text(json.dumps(meta))
    return root,fixture,meta


@pytest.mark.parametrize('bad',['personal','wrong_model','tampered_header','unbounded','wrong_baseline'])
def test_diagnostic_rejects_untrusted_or_unbounded_fixture_before_mutation(tmp_path,bad):
    root,fixture,meta=inputs(tmp_path)
    if bad=='personal':meta['synthetic_only']=False
    elif bad=='wrong_model':meta['model_sha256']='0'*64
    elif bad=='tampered_header':(fixture/'gobot_mww_fixture.h').write_text('changed')
    elif bad=='wrong_baseline':meta['kernel_baseline']='native_reference'
    else:meta['invocations']=4097
    (fixture/'fixture.json').write_text(json.dumps(meta))
    before=(root/'main/gobot_mww_config.h').read_bytes()
    with pytest.raises(ValueError):m.prepare(root,fixture)
    assert (root/'main/gobot_mww_config.h').read_bytes()==before
    assert not (root/'main/gobot_mww_fixture.h').exists()


def test_diagnostic_rejects_production_wake_source(tmp_path):
    root,fixture,_=inputs(tmp_path)
    path=root/'main/gobot_mww_config.h';path.write_text('#define GOBOT_WAKE_ROUTE 1\n#define GOBOT_WAKE_OWNER_TEST 1')
    with pytest.raises(ValueError,match='Production route'):m.prepare(root,fixture)
    assert not (root/'main/gobot_mww_fixture.h').exists()
