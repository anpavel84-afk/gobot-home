import hashlib,importlib.util,json
from pathlib import Path
import pytest
FILE=Path(__file__).resolve().parents[1]/'firmware/spotpear/microwake/prepare_product.py'
spec=importlib.util.spec_from_file_location('prepare_wake_product',FILE);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)

def fixture(tmp_path,passed=False):
    root=tmp_path/'source';(root/'main').mkdir(parents=True)
    for p in (root/'CMakeLists.txt',root/'main/gobot_build_info.h'):p.write_text('0.4.5-dev-fast-start-1')
    model=tmp_path/'model';model.mkdir();blob=b'fixture-model-not-real'
    (model/'gobot.tflite').write_bytes(blob);sha=hashlib.sha256(blob).hexdigest()
    (model/'stream-report.json').write_text(json.dumps({'sha256':sha,'window':3,'candidate_passed':passed,'cutoff':250}))
    (model/'model.json').write_text(json.dumps({'context_frames':120}))
    (model/'ambient.json').write_text(json.dumps({'seconds':1800,'false_events':0,'model_sha256':sha}))
    return root,model,sha

def test_failed_model_remains_diagnostic_and_preserves_current_baseline(tmp_path):
    root,model,_=fixture(tmp_path)
    mod.prepare(root,model)
    assert '#define GOBOT_WAKE_ROUTE 0' in (root/'main/gobot_mww_config.h').read_text()
    assert 'warm>=40' in (root/'main/gobot_mww.cc').read_text()
    assert 'WakeQuestionBuffer' in (root/'main/gobot_mww.cc').read_text()

@pytest.mark.parametrize('passed,human_ok,ambient_ok',[(False,True,True),(True,False,True),(True,True,False)])
def test_no_routing_without_exact_quality_and_human_evidence(tmp_path,passed,human_ok,ambient_ok):
    root,model,sha=fixture(tmp_path,passed)
    human=tmp_path/'human.json';human.write_text(json.dumps({'human_labels_verified':human_ok,'positive_trials':30,'true_positive_count':30,'false_positive_count':0,'negative_observation_seconds':7200,'model_sha256':sha}))
    if not ambient_ok:(model/'ambient.json').write_text(json.dumps({'seconds':1800,'false_events':0,'model_sha256':'another-model'}))
    with pytest.raises(ValueError):mod.prepare(root,model,True,human)
    assert '0.4.5' in (root/'CMakeLists.txt').read_text()

def test_matching_passing_evidence_can_enable_the_existing_wake_path(tmp_path):
    root,model,sha=fixture(tmp_path,True)
    human=tmp_path/'human.json';human.write_text(json.dumps({'human_labels_verified':True,'positive_trials':30,'true_positive_count':29,'false_positive_count':0,'negative_observation_seconds':7200,'model_sha256':sha}))
    mod.prepare(root,model,True,human)
    assert '#define GOBOT_WAKE_ROUTE 1' in (root/'main/gobot_mww_config.h').read_text()
