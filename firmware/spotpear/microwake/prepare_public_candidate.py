"""Prepare a COPY of0.4.11 only after fixed-policy synthetic ordinary/alias pass.

This is a local acoustic candidate, never production/human acceptance or spending
permission. Preserves touch/Brain/audio, native parity gate and wake routing OFF.
"""
import argparse,hashlib,json,shutil
from pathlib import Path
from prepare_product import change
from public_data_scope import public_training_scope
VERSION='0.4.12-dev-public-wake-1'


def check_report(report,metadata,blob):
    sha=hashlib.sha256(blob).hexdigest()
    iq=metadata.get('input_quantization',[0,0]);oq=metadata.get('output_quantization',[0,0])
    if len(iq)!=2 or len(oq)!=2 or abs(iq[0]-26/255)>1e-7 or iq[1]!=-128 or abs(oq[0]-1/256)>1e-7 or oq[1]!=0:raise ValueError('Quantization differs from installed native converter')
    if not public_training_scope(metadata) or metadata.get('context_frames')!=204 or metadata.get('sha256')!=sha or report.get('sha256')!=sha or report.get('kernel_baseline')!='native_reference' or report.get('candidate_passed') is not True or report.get('cutoff')!=231 or report.get('window')!=10 or not 50000<=len(blob)<=131072:raise ValueError('Require qualified fixed-policy public model')
    if metadata.get('public_human_negative_training'):
        row=report.get('public_speech_negative',{})
        if row.get('positive')!=0 or row.get('negative',0)<100 or row.get('false_events')!=0:raise ValueError('Licensed public speech acceptance missing/failed')
    for group,speaker,positive,negative in [('validation','aleksandr',75,498),('test','elena',75,498),('alias_validation','aleksandr',20,0),('alias_validation','elena',20,0)]:
        row=report.get(group,{}).get(speaker,{})
        if row.get('positive')!=positive or row.get('negative')!=negative or row.get('tp',0)<.9*positive or row.get('false_events')!=0:raise ValueError('Ordinary/alias synthetic acceptance failed')
    return sha


def prepare(root,model,fixture):
    main=root/'main';blob=(model/'gobot.tflite').read_bytes()
    report=json.loads((model/'stream-reference-report.json').read_text());metadata=json.loads((model/'model.json').read_text())
    sha=check_report(report,metadata,blob)
    if '0.4.11-dev-ref-parity-1' not in (root/'CMakeLists.txt').read_text():raise ValueError('Expected isolated current source copy')
    config=(main/'gobot_mww_config.h').read_text()
    if '#define GOBOT_WAKE_ROUTE 0' not in config or '#define GOBOT_WAKE_OWNER_TEST 0' not in config:raise ValueError('No cloud admission in acoustic candidate')
    old=(main/'gobot_mww.tflite').read_bytes()
    actual_slot=len(old)==131072 and hashlib.sha256(old[:60912]).hexdigest()=='4ffc532e16b3e20b7ce09099338023b5af304a0e31bf537034bb03dd67a4c5f9' and not any(old[60912:])
    if len(old)!=131072 or not (actual_slot or hashlib.sha256(old).hexdigest()=='1e26ad59e1a9a5773b0310fc03d5b689dfa575b7f1521aa63e9299239b27e2e4'):raise ValueError('Unexpected installed public model slot')
    proof=json.loads((fixture/'fixture.json').read_text());header=fixture/'gobot_mww_fixture.h'
    if proof.get('synthetic_only') is not True or proof.get('model_sha256')!=sha or proof.get('kernel_baseline')!='native_reference' or not 500<=proof.get('invocations',0)<=4096 or hashlib.sha256(header.read_bytes()).hexdigest()!=proof.get('header_sha256'):raise ValueError('Require matching bounded native reference fixture')
    (main/'gobot_mww.tflite').write_bytes(blob+bytes(131072-len(blob)));shutil.copy2(header,main/header.name)
    for p in (root/'CMakeLists.txt',main/'gobot_build_info.h'):change(p,'0.4.11-dev-ref-parity-1',VERSION)
    result={'version':VERSION,'model_sha256':sha,'public_synthetic_only':not metadata.get('public_human_negative_training',False),'public_licensed_speech_negative_training':metadata.get('public_human_negative_training',False),'contains_personal_weights':False,'synthetic_acceptance':True,'production_qualified':False,'human_accepted':False,'trial_compiled':False,'wake_route':False,'kernel_baseline':'native_reference','fixture_invocations':proof['invocations'],'fixture_header_sha256':proof['header_sha256'],'native_tolerance':3,'previous_app_sha256':'2695a0b436e9db3e04e8f67fa1b2718a34232e4c4531f965c2e5dc137df7cbe5','flashed':False,'paid_calls':0}
    (root/'public-wake-candidate.json').write_text(json.dumps(result,indent=2));return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('source_copy','model','fixture'):p.add_argument(key,type=Path)
    a=p.parse_args();prepare(a.source_copy,a.model,a.fixture)
