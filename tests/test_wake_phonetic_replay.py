import ast
from pathlib import Path
import numpy as np
import pytest


def make_fragment():
    path=Path('firmware/spotpear/microwake/phonetic_replay.py')
    node=next(n for n in ast.parse(path.read_text(encoding='utf-8')).body if isinstance(n,ast.FunctionDef) and n.name=='fragment')
    ns={'np':np,'trim_background':lambda raw:raw};exec(compile(ast.Module(body=[node],type_ignores=[]),str(path),'exec'),ns)
    return ns['fragment']


def test_partial_negative_never_contains_whole_word_or_modifies_source():
    raw=np.arange(16000,dtype=np.int16);copy=raw.copy();rng=np.random.default_rng(7)
    for _ in range(50):
        part=make_fragment()(raw,rng)
        assert .25*len(raw)-1<=len(part)<=.45*len(raw)
        assert np.array_equal(part,raw[:len(part)]) or np.array_equal(part,raw[-len(part):])
    assert np.array_equal(raw,copy)


def test_empty_or_too_short_name_cannot_be_a_partial_negative():
    with pytest.raises(ValueError):make_fragment()(np.ones(200),np.random.default_rng(4))
