"""Regression for the empty-foreground crash in background-only augmentation."""
import ast
from pathlib import Path
import numpy as np


def test_background_window_has_audio_without_an_interpolation_source():
    source=Path('firmware/spotpear/microwake/train_reference.py').read_text(encoding='utf-8')
    function=next(node for node in ast.parse(source).body if isinstance(node,ast.FunctionDef) and node.name=='window')
    captured=[]
    def frontend(samples):
        captured.append(samples.copy());return np.zeros((204,40),np.float32)
    namespace={'np':np,'FRAMES':204,'TAIL_SAMPLES':9600,'features':frontend,'lfilter':lambda a,b,signal:signal}
    exec(compile(ast.Module(body=[function],type_ignores=[]),'<background-augmentation>','exec'),namespace)
    features=namespace['window'](None,np.random.default_rng(5),False)
    assert features.shape==(204,40)
    assert len(captured)==1 and len(captured[0])>204*160 and captured[0].any()
