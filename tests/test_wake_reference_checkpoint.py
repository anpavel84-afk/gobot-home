"""Checkpoint choice must never export an untrained network as trained."""
import ast
from pathlib import Path
import math
from types import SimpleNamespace
import pytest


def selector():
    source=Path('firmware/spotpear/microwake/train_reference.py').read_text(encoding='utf-8')
    tree=ast.parse(source)
    function=next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=='select_checkpoint')
    namespace={'np':SimpleNamespace(isfinite=math.isfinite)}
    exec(compile(ast.Module(body=[function],type_ignores=[]),'<checkpoint-selection>','exec'),namespace)
    return namespace['select_checkpoint']


def test_initialization_is_never_selected_when_it_beats_training():
    rows=[{'step':0,'validation_bce':.69},{'step':1000,'validation_bce':1.27},{'step':2000,'validation_bce':1.0}]
    assert selector()(rows)==rows[2]


def test_no_finite_trained_checkpoint_is_a_failure():
    with pytest.raises(ValueError,match='No finite trained'):
        selector()([{'step':0,'validation_bce':.69},{'step':1000,'validation_bce':float('nan')}])
