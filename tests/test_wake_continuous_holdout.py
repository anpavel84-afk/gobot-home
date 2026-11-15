"""Longer context must not leak an adjacent held-out wake utterance."""
import importlib.util
from pathlib import Path
import numpy as np


def test_full_reference_context_excludes_nearby_holdout_audio():
    path=Path('firmware/spotpear/microwake/continuous_replay.py')
    spec=importlib.util.spec_from_file_location('continuous_holdout',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    positives=[[2+i*1.5,2.7+i*1.5] for i in range(10)]
    rows=np.repeat(np.arange(4000,dtype=np.float32)[:,None],40,axis=1)
    positive,negative=module.windows(rows,positives,[[25,35]],np.random.default_rng(42),count=128,frames=204)
    excluded=set()
    for i in (4,9):
        a,b=positives[i];excluded.update(range(int(a*100)-2,int(np.ceil(b*100))))
    assert all(not excluded.intersection(sample[:,0].astype(int)) for sample in positive+negative)
    assert all(sample.shape==(204,40) for sample in positive+negative)
    pcm=np.ones(40000,dtype=np.int16)
    masked=module.training_audio(pcm,positives,[[20,21]],rate=1000)
    for a,b in [positives[4],positives[9],[20,21]]:
        assert not masked[int(a*1000):int(b*1000)].any()
    assert pcm.all() and masked[25000:35000].all()
