import importlib.util
from pathlib import Path
import numpy as np

p=Path(__file__).resolve().parents[1]/'firmware/spotpear/microwake/word_guard.py'
s=importlib.util.spec_from_file_location('word_guard_reference',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)


def pattern():
    x=np.random.default_rng(817).normal(size=(80,12)).astype(np.float32)
    return x/np.linalg.norm(x,axis=1,keepdims=True)


def test_whole_word_in_longer_input_matches():
    word=pattern();query=np.concatenate([np.zeros((30,12)),word,np.zeros((30,12))]).astype(np.float32)
    assert m.scores(word[None],query)[0]<1e-5


def test_short_fragment_cannot_complete_word():
    word=pattern()
    assert np.isinf(m.scores(word[None],word[:15])[0])


def test_phonetic_order_matters():
    word=pattern()
    assert m.scores(word[None],word[::-1].copy())[0]>.1


def test_reasonable_time_compression_remains_matchable():
    word=pattern()
    assert np.isfinite(m.scores(word[None],word[::2].copy())[0])
