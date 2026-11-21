import ast,math
from pathlib import Path
import pytest


def validate():
    path=Path('firmware/spotpear/microwake/field_personal_adaptation.py')
    node=next(n for n in ast.parse(path.read_text(encoding='utf-8')).body if isinstance(n,ast.FunctionDef) and n.name=='validate_plan')
    ns={'math':math};exec(compile(ast.Module(body=[node],type_ignores=[]),str(path),'exec'),ns)
    return ns['validate_plan']


@pytest.mark.parametrize('failure',[None,'expired','unconfirmed','domain','holdout_overlap','missing_keyword','false_truth'])
def test_field_training_scope_has_two_train_one_holdout_and_original_expiry(failure):
    meta={'capture_domain':'mono_pcm16_pre_afe','protocol':'field_failed_wake_recheck','capture_state':'complete_crc_verified','owner_reported_completion':True,'expires_at':200}
    plan={'schema':'field_recheck_v1','human_labels_verified':False,'positive_segments':[[1.5,2.5],[6,7],[10,11]],'question_segments':[[1.5,4],[6,8],[10,12]],'negative_segments':[[14,22]]}
    if failure=='expired':meta['expires_at']=99
    if failure=='unconfirmed':meta['owner_reported_completion']=False
    if failure=='domain':meta['capture_domain']='post_afe_opus'
    if failure=='holdout_overlap':plan['negative_segments']=[[11,19]]
    if failure=='missing_keyword':plan['positive_segments'].pop()
    if failure=='false_truth':plan['human_labels_verified']=True
    if failure:
        with pytest.raises(ValueError):validate()(meta,plan,30,100)
    else:
        train,heldout,negative,negative_holdout=validate()(meta,plan,30,100)
        assert train==[0,1] and heldout==[2] and negative[1]<negative_holdout[0]
