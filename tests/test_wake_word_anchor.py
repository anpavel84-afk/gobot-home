import importlib.util
from pathlib import Path
import numpy as np
import pytest

path=Path(__file__).resolve().parents[1]/'firmware/spotpear/microwake/augmentation.py'
spec=importlib.util.spec_from_file_location('anchor_augmentation',path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


def test_following_question_does_not_move_or_overwrite_keyword_endpoint():
    background=np.zeros(100);keyword=np.arange(1,41);following=np.ones(200)*500
    result=m.place_keyword(background,keyword,following,end=70)
    np.testing.assert_array_equal(result[30:70],keyword)
    np.testing.assert_array_equal(result[70:],following[:30])
    assert not np.any(result[:30]) and not np.any(background)


@pytest.mark.parametrize('end',[0,20,101])
def test_incomplete_keyword_or_unbounded_placement_refused(end):
    with pytest.raises(ValueError):m.place_keyword(np.zeros(100),np.ones(40),np.ones(20),end=end)
