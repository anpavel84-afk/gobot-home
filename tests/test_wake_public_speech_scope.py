import ast,hashlib,importlib.util,json,re
from pathlib import Path
import numpy as np
import pytest

BASE=Path('firmware/spotpear/microwake')
spec=importlib.util.spec_from_file_location('licensed_wake_scope',BASE/'public_data_scope.py');scope=importlib.util.module_from_spec(spec);spec.loader.exec_module(scope)


def test_public_recorded_speech_is_distinct_from_private_owner_training():
    assert scope.public_training_scope({'human_training':False})
    public={'human_training':True,'owner_human_training':False,'public_human_negative_training':True,'public_speech_source_md5':scope.MD5,'public_speech_source_url':scope.URL,'public_speech_license':'CC-BY-4.0'}
    assert scope.public_training_scope(public)
    assert not scope.public_training_scope({**public,'owner_human_training':True})
    assert not scope.public_training_scope({**public,'public_speech_source_md5':'foreign'})
    assert not scope.public_training_scope({'human_training':True})


@pytest.mark.parametrize('failure',[None,'owner_audio','hop','overlap','license','origin','hash'])
def test_native_licensed_replay_scope_and_voice_split(tmp_path,failure):
    path=tmp_path/'training.npy';path.write_bytes(bytes(2048))
    info={'schema':'licensed-public-speech-native-v1','license':'CC-BY-4.0','source_url':scope.URL,'source_md5':scope.MD5,'owner_audio':False,'split':'training','frontend_hop_samples':160,'context_frames':204,'windows':1000,'speakers':[str(i) for i in range(32)],'excluded_speakers':[str(i) for i in range(32,40)],'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    if failure=='owner_audio':info['owner_audio']=True
    if failure=='hop':info['frontend_hop_samples']=320
    if failure=='overlap':info['excluded_speakers'][0]='0'
    if failure=='license':info['license']='CC-BY-NC-4.0'
    if failure=='origin':info['source_md5']='0'*32
    if failure=='hash':path.write_bytes(bytes(2049))
    path.with_suffix('.json').write_text(json.dumps(info))
    if failure:
        with pytest.raises(ValueError):scope.validate_speech_replay(path)
    else:assert scope.validate_speech_replay(path)==info


def test_chunked_feature_append_preserves_both_partial_last_chunks(tmp_path):
    node=next(n for n in ast.parse((BASE/'train_reference.py').read_text(encoding='utf-8')).body if isinstance(n,ast.FunctionDef) and n.name=='append_features')
    ns={'np':np};exec(compile(ast.Module(body=[node],type_ignores=[]),'<append>','exec'),ns)
    a=np.ones((1025,2,3),np.float16);b=np.full((1025,2,3),7,np.float16)
    joined=ns['append_features'](a,b,tmp_path/'joined.npy')
    assert joined.shape==(2050,2,3) and np.array_equal(joined[:1025],a) and np.array_equal(joined[1025:],b)


def test_real_background_transcripts_cannot_include_target_names():
    node=next(n for n in ast.parse((BASE/'public_speech.py').read_text(encoding='utf-8')).body if isinstance(n,ast.FunctionDef) and n.name=='permitted_text')
    ns={'re':re};exec(compile(ast.Module(body=[node],type_ignores=[]),'<transcript-filter>','exec'),ns)
    for text in ('GO BOT COME HERE','GABOT','GOBOT','GA BOT'):assert not ns['permitted_text'](text)
    assert ns['permitted_text']('THE ROBOT WAS READY')
