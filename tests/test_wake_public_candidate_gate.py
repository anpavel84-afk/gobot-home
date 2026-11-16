import ast,hashlib
import importlib.util
from pathlib import Path
import pytest


@pytest.mark.parametrize('failure',[None,'false_wake','missed_alias','kernel','threshold','private','forged_pass','quantization','licensed_valid','licensed_missing_control'])
def test_no_install_preparation_for_failed_public_model(failure):
    source=Path('firmware/spotpear/microwake/prepare_public_candidate.py').read_text(encoding='utf-8')
    function=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='check_report')
    scope=Path('firmware/spotpear/microwake/public_data_scope.py');spec=importlib.util.spec_from_file_location('public_scope_gate',scope);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    ns={'hashlib':hashlib,'public_training_scope':module.public_training_scope};exec(compile(ast.Module(body=[function],type_ignores=[]),'<public-candidate>','exec'),ns)
    blob=bytes(60912);sha=hashlib.sha256(blob).hexdigest();metadata={'human_training':False,'context_frames':204,'sha256':sha,'input_quantization':[26/255,-128],'output_quantization':[1/256,0]}
    report={'sha256':sha,'kernel_baseline':'native_reference','candidate_passed':True,'cutoff':231,'window':10,'validation':{'aleksandr':{'positive':75,'tp':75,'negative':498,'false_events':0}},'test':{'elena':{'positive':75,'tp':75,'negative':498,'false_events':0}},'alias_validation':{s:{'positive':20,'tp':20,'negative':0,'false_events':0} for s in ('aleksandr','elena')}}
    if failure=='false_wake':report['test']['elena']['false_events']=1
    if failure=='missed_alias':report['alias_validation']['aleksandr']['tp']=8
    if failure=='kernel':report['kernel_baseline']='desktop_optimized'
    if failure=='threshold':report['cutoff']=200
    if failure=='private':metadata['human_training']=True
    if failure=='forged_pass':report['candidate_passed']=False
    if failure=='quantization':metadata['input_quantization']=[.05,-128]
    if failure in ('licensed_valid','licensed_missing_control'):
        metadata.update(human_training=True,owner_human_training=False,public_human_negative_training=True,public_speech_source_md5=module.MD5,public_speech_source_url=module.URL,public_speech_license='CC-BY-4.0')
        if failure=='licensed_valid':report['public_speech_negative']={'positive':0,'negative':200,'false_events':0}
    if failure not in (None,'licensed_valid'):
        with pytest.raises(ValueError):ns['check_report'](report,metadata,blob)
    else:assert ns['check_report'](report,metadata,blob)==sha
