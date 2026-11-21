"""Invalid diagnostics must fail before any recording/model is accessed."""
import ast
from pathlib import Path
import pytest


def evaluator():
    p=Path(__file__).resolve().parents[1]/'firmware/spotpear/microwake/evaluate_local_sample.py'
    tree=ast.parse(p.read_text(encoding='utf-8'))
    node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='evaluate')
    def no_file_access(*args):raise AssertionError('Recording accessed before option validation')
    namespace={'paths':no_file_access}
    exec(compile(ast.Module(body=[node],type_ignores=[]),str(p),'exec'),namespace)
    return namespace['evaluate']


@pytest.mark.parametrize('options',[
    {'input_gain':10},
    {'candidate_sha':'a'*64,'encrypted_model':False},
    {'background_prefix_seconds':10000},
])
def test_unsafe_or_unbounded_evaluation_refused_before_data_access(options):
    with pytest.raises(ValueError):evaluator()('not-a-real-sample','unused',**options)
