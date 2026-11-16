import ast,hashlib,json,importlib.util
from pathlib import Path
import pytest
import numpy as np
from types import SimpleNamespace


def validator():
    path=Path('firmware/spotpear/microwake/refine_continuous.py')
    node=next(n for n in ast.parse(path.read_text(encoding='utf-8')).body if isinstance(n,ast.FunctionDef) and n.name=='validate_sources')
    spec=importlib.util.spec_from_file_location('correction_public_scope',path.with_name('public_data_scope.py'));module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    ns={'json':json,'hashlib':hashlib,'public_training_scope':module.public_training_scope};exec(compile(ast.Module(body=[node],type_ignores=[]),str(path),'exec'),ns)
    return ns['validate_sources']


@pytest.mark.parametrize('failure',[None,'human','heldout','alignment','changed_hard','teacher'])
def test_correction_is_bound_to_public_teacher_and_train_split(tmp_path,failure):
    source=tmp_path/'source';source.mkdir();hard=tmp_path/'hard.npy';hard.write_bytes(b'public-features')
    train=['denis','dmitri','espeak-ru','anna','irina'];blob=b'public-model';(source/'gobot.tflite').write_bytes(blob)
    sha=hashlib.sha256(blob).hexdigest();config={'human_training':False,'training_speakers':train,'alias_positive_total':1000}
    meta={'synthetic_only':True,'training_speakers':train,'excluded_speakers':['aleksandr','elena'],'kernel_baseline':'native_reference','stream_offline_alignment_frames':1,'sha256':hashlib.sha256(hard.read_bytes()).hexdigest(),'source_model_sha256':sha}
    if failure=='human':config['human_training']=True
    if failure=='heldout':meta['training_speakers']=['elena',*train[1:]]
    if failure=='alignment':meta['stream_offline_alignment_frames']=0
    if failure=='changed_hard':hard.write_bytes(b'changed')
    if failure=='teacher':meta['source_model_sha256']='0'*64
    (source/'config.json').write_text(json.dumps(config));(source/'model.json').write_text(json.dumps({'sha256':sha}));hard.with_suffix('.json').write_text(json.dumps(meta))
    if failure:
        with pytest.raises(ValueError):validator()(source,hard)
    else:assert validator()(source,hard)==(config,meta)


def test_alias_rows_recover_exact_original_schedule_without_labels_leaking():
    source=Path('firmware/spotpear/microwake/train_reference.py').read_text(encoding='utf-8')
    schedule=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='source_schedule')
    ns={'np':np};exec(compile(ast.Module(body=[schedule],type_ignores=[]),'<schedule>','exec'),ns)
    code=Path('firmware/spotpear/microwake/refine_continuous.py').read_text(encoding='utf-8')
    function=next(n for n in ast.parse(code).body if isinstance(n,ast.FunctionDef) and n.name=='alias_indices')
    ns['reference']=SimpleNamespace(SEED=20261114,source_schedule=ns['source_schedule'])
    exec(compile(ast.Module(body=[function],type_ignores=[]),'<aliases>','exec'),ns)
    y=np.arange(102000)%2;np.random.default_rng(20261114).shuffle(y)
    ids=ns['alias_indices'](y)
    assert len(ids)==len(np.unique(ids))==1000 and np.all(y[ids]==1)
    assert np.array_equal(ns['alias_indices'](np.pad(y,(0,1000))),ids)
    y[0]=1-y[0]
    with pytest.raises(ValueError,match='schedule'):ns['alias_indices'](y)
