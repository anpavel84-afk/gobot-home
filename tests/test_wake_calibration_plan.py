import copy,importlib.util
from pathlib import Path
import pytest
FILE=Path(__file__).resolve().parents[1]/'firmware/spotpear/microwake/calibration_plan.py'
spec=importlib.util.spec_from_file_location('wake_calibration',FILE);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def plan():
    return {'capture_domain':'mono_pcm16_pre_afe','human_labels_verified':False,
        'positive_segments':[[i,i+.5] for i in range(10)],'negative_segments':[[12,13]],'heldout_isolated_indices':[4,9]}

def test_calibration_keeps_fixed_holdout_and_provisional_labels():
    p=plan();assert len(m.validate(p,15)[0])==10

@pytest.mark.parametrize('key,value',[
    ('capture_domain','post_afe_opus'),('human_labels_verified',True),
    ('negative_segments',[[4.1,4.4]]),('negative_segments',[[14,16]]),
    ('positive_segments',[[0,.5]]),('heldout_isolated_indices',[0,1]),
    ('negative_segments',[[float('nan'),13]]),
])
def test_invalid_or_leaking_labels_rejected(key,value):
    p=copy.deepcopy(plan());p[key]=value
    with pytest.raises(ValueError):m.validate(p,15)
