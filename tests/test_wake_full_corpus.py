"""Public-only full-scale plan, complete coverage, lazy loading and split guards."""
import ast
import json
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


def test_short_audible_negative_is_padded_without_changing_speech():
    normalize=extract('full_corpus.py',['normalize_clip'],{'np':np})['normalize_clip']
    raw=np.full(3160,7000,dtype='<i2');result=normalize(raw,'negative')
    assert len(result)==3200 and np.array_equal(result[:3160],raw) and not result[3160:].any()
    for invalid,label in [(raw,'positive'),(np.zeros(4000,dtype='<i2'),'negative'),(raw[:1000],'negative')]:
        with pytest.raises(ValueError):normalize(invalid,label)


def test_gabot_aliases_are_balanced_and_heldout_voices_excluded():
    namespace=extract('alias_corpus.py',['alias_plan'],{'np':np,'SPEAKERS':('denis','dmitri','espeak-ru','anna','irina'),
        'GABOT_VARIANTS':('Га́бот.','Габо́т.')})
    plan=namespace['alias_plan'];rows=plan('denis')
    assert rows==plan('denis') and len(rows)==200
    assert len({r['file'] for r in rows})==200
    assert {word:sum(r['text']==word for r in rows) for word in namespace['GABOT_VARIANTS']}=={'Га́бот.':100,'Габо́т.':100}
    assert len(plan('elena',heldout=True))==20
    with pytest.raises(ValueError):plan('elena')
    with pytest.raises(ValueError):plan('denis',heldout=True)


def test_alias_model_cannot_skip_alias_acceptance(tmp_path):
    (tmp_path/'config.json').write_text(json.dumps({'alias_positive_total':1000}))
    evaluate=extract('validate_reference.py',['main'],{'json':json})['main']
    with pytest.raises(ValueError,match='held-out alias'):
        evaluate(tmp_path,tmp_path,'native_reference')
