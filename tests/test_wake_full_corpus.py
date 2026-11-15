"""Public-only full-scale plan, complete coverage, lazy loading and split guards."""
import ast
from pathlib import Path
import numpy as np
import pytest

BASE=Path('firmware/spotpear/microwake')


def extract(file,names,namespace):
    tree=ast.parse((BASE/file).read_text(encoding='utf-8'))
    nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names]
    assert len(nodes)==len(names)
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(file),'exec'),namespace)
    return namespace


def planner():
    variants=ast.literal_eval(next(n.value for n in ast.parse((BASE/'wake_variants.py').read_text(encoding='utf-8')).body if isinstance(n,ast.Assign) and n.targets[0].id=='VARIANTS'))
    return extract('full_corpus.py',['plan'],{'np':np,'SEED':20261115,'SPEAKERS':('denis','dmitri','espeak-ru','anna','irina'),
        'COUNTS':{'positive':10000,'negative':2000},'VARIANTS':variants,'phrases':lambda:([],['погода','готов','робот'])})['plan']


def test_full_plan_is_finite_distinct_and_reproducible():
    plan=planner();rows=plan('denis')
    assert rows==plan('denis') and len(rows)==12000
    assert len({r['file'] for r in rows})==12000
    for label,count in [('positive',10000),('negative',2000)]:
        subset=[r for r in rows if r['label']==label]
        assert len(subset)==count
        assert len({(r['text'],r['speed'],r['pitch']) for r in subset})==count
    assert all(70<=r['speed']<=130 and -20<=r['pitch']<=20 for r in rows)


@pytest.mark.parametrize('speaker',['aleksandr','elena','owner','../denis'])
def test_heldout_or_private_voice_cannot_enter_generation(speaker):
    with pytest.raises(ValueError,match='TRAIN'):planner()(speaker)


def test_full_positive_schedule_covers_every_source_once():
    function=extract('train_reference.py',['source_schedule'],{'np':np})['source_schedule']
    groups={0:range(10000),1:range(50000)}
    result=function(groups,100000,np.random.default_rng(9))
    assert len(result[0])==len(result[1])==50000
    assert np.array_equal(np.sort(result[1]),np.arange(50000))
    assert np.array_equal(np.bincount(result[0]),np.full(10000,5))


def test_lazy_loading_reads_only_selected_clip(tmp_path):
    loader=extract('train_reference.py',['load_clip'],{'np':np,'Path':Path})['load_clip']
    raw=np.arange(200,dtype='<i2');path=tmp_path/'public.pcm';path.write_bytes(raw.tobytes())
    assert np.array_equal(loader(path),raw)
    assert loader(raw) is raw


def test_full_profile_cannot_reuse_pilot_or_private_weights():
    namespace=extract('train_reference.py',['main'],{})
    with pytest.raises(ValueError,match='fresh bounded'):
        namespace['main'](None,None,full_corpus=True,expanded=True,word_anchored=True,count=100000,initial_weights=Path('private.weights.h5'))
