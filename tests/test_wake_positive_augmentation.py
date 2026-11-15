import importlib.util
from pathlib import Path
import numpy as np
import pytest
FILE=Path(__file__).resolve().parents[1]/'firmware/spotpear/microwake/augmentation.py'
spec=importlib.util.spec_from_file_location('wake_augmentation',FILE);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def test_long_word_keeps_beginning_and_ending_instead_of_tail_crop():
    word=np.arange(32000,dtype=float);out=m.fit_positive(word,12320)
    assert len(out)==12320 and out[0]==word[0] and out[-1]==word[-1]
    assert np.all(np.diff(out)>0) and np.array_equal(word,np.arange(32000))

def test_short_word_remains_complete():
    word=np.array([10,20,30]);assert np.array_equal(m.fit_positive(word,100),word)

def test_invalid_window_rejected():
    with pytest.raises(ValueError):m.fit_positive(np.arange(10),1)

def test_quiet_initial_and_final_consonants_are_not_background_cropped():
    word=np.concatenate([np.full(1000,10.),np.full(2000,12000.),np.full(1000,10.)])
    np.testing.assert_array_equal(m.trim_background(word,retain_full=True),word)
    assert len(m.trim_background(word))<len(word)
