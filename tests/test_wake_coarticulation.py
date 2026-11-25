import importlib.util
from pathlib import Path
import numpy as np


def test_following_speech_keeps_every_wake_sample_and_bounds_the_suffix():
    spec=importlib.util.spec_from_file_location('wake_coarticulation',Path('firmware/spotpear/microwake/coarticulation.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    word=np.arange(-2000,2000,dtype=np.int16);before=word.copy()
    suffix=np.full(16000,1000,dtype=np.int16)
    result=module.append_speech(word,suffix,np.random.default_rng(5))
    np.testing.assert_array_equal(result[:len(word)],word)
    np.testing.assert_array_equal(word,before)
    assert len(word)+8000<=len(result)<=len(word)+8000+320
    assert np.any(result[len(word):]) and np.max(abs(result))<=32768


def test_negative_mining_cannot_label_audio_outside_negative_intervals():
    spec=importlib.util.spec_from_file_location('wake_negative_mining',Path('firmware/spotpear/microwake/coarticulation.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    clip=np.full(16000*10,10,dtype=np.int16);clip[16000:32000]=1000
    before=clip.copy();windows=module.negative_speech_windows([clip])
    assert len(windows)>1
    np.testing.assert_array_equal(clip,before)
    assert all(set(np.unique(window))<=set(np.unique(clip)) for window in windows)
    assert any(np.sqrt(np.mean(window.astype(float)**2))>500 for window in windows[1:])
