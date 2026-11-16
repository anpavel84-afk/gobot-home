import importlib.util
from pathlib import Path
import numpy as np
import pytest
FILE=Path(__file__).resolve().parents[1]/'firmware/spotpear/microwake/continuous_replay.py'
spec=importlib.util.spec_from_file_location('continuous_wake',FILE);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def test_holdout_not_selected_and_negatives_do_not_cross_labels():
    rows=np.arange(4000)[:,None].repeat(40,axis=1)
    positives=[[i*2+1,i*2+1.5] for i in range(10)]
    pos,neg=m.windows(rows,positives,[[24,25],[28,29]],np.random.default_rng(1),count=128)
    for p in pos:
        end=int(p[-1,0])+1
        assert all(abs(end-int(positives[i][1]*100))>20 for i in [4,9])
    for n in neg:assert (2400<=n[0,0]<=n[-1,0]<2500) or (2800<=n[0,0]<=n[-1,0]<2900)

def test_short_negative_not_silently_mixed_with_prior_speech():
    with pytest.raises(ValueError):m.windows(np.zeros((3000,40)),[[i*2+1,i*2+1.5] for i in range(10)],[[24,24.3]],np.random.default_rng(1))
