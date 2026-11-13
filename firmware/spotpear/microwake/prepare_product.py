"""Reuse current fast-start UI/audio. Never flash or bypass failed KWS evidence."""
import argparse,hashlib,json,shutil
from pathlib import Path
HERE=Path(__file__).resolve().parent

def change(path,old,new):
    s=path.read_text()
    if s.count(old)!=1:raise ValueError('Unexpected current firmware: '+path.name)
    path.write_text(s.replace(old,new))

def prepare(root,model_dir,voice_route=False,human_report=None):
    main=root/'main'
    if '0.4.5-dev-fast-start-1' not in (root/'CMakeLists.txt').read_text():raise ValueError('Copy installed fast-start source first')
    report=json.loads((model_dir/'stream-report.json').read_text());blob=(model_dir/'gobot.tflite').read_bytes()
    if hashlib.sha256(blob).hexdigest()!=report['sha256'] or report['window']!=3:raise ValueError('Model/evidence mismatch')
    if voice_route:
        ambient=json.loads((model_dir/'ambient.json').read_text())
        human=json.loads(human_report.read_text()) if human_report else {}
        if not (report['candidate_passed'] and ambient['seconds']>=1800 and ambient['false_events']==0 and ambient.get('model_sha256')==report['sha256']
            and human.get('human_labels_verified') is True and human.get('positive_trials',0)>=30
            and human.get('true_positive_count',0)>=.9*human['positive_trials'] and human.get('false_positive_count')==0
            and human.get('negative_observation_seconds',0)>=7200
            and human.get('model_sha256')==report['sha256']):
            raise ValueError('Wake routing requires passing synthetic/background and labelled human evidence')
    # Existing ring + native frontend/runtime, not another KWS or voice stack.
    for name in ('gobot_mww.cc','gobot_mww.h','wake_question_buffer.h'):shutil.copy2(HERE/name,main/name)
    (main/'gobot_mww.tflite').write_bytes(blob)
    metadata=json.loads((model_dir/'model.json').read_text())
    warmup=max(25,(int(metadata.get('context_frames',75))+2)//3)
    change(main/'gobot_mww.cc','if(++warm>=25 &&','if(++warm>='+str(warmup)+' &&')
    (main/'gobot_mww_config.h').write_text(f'#define GOBOT_FEATURE_HASH 1987024791u\n#define GOBOT_WAKE_CUTOFF {int(report["cutoff"])}\n#define GOBOT_WAKE_ROUTE {int(voice_route)}\n')
    # Fast-start already retains audio from activation. A real wake preserves
    # the rolling prefix until that same AudioService consumes it once.
    for path in (root/'CMakeLists.txt',main/'gobot_build_info.h'):
        change(path,'0.4.5-dev-fast-start-1','0.4.6-dev-wake-product')
    (root/'wake-product-manifest.json').write_text(json.dumps({'version':'0.4.6-dev-wake-product',
        'model_sha256':report['sha256'],'wake_route':voice_route,'warmup_invocations':warmup,
        'prefix_ms':1000,'buffer_ms':12000,'fast_start_preserved':True,'flashed':False},indent=2))

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('copy_of_fast_start',type=Path);a.add_argument('model',type=Path)
    a.add_argument('--voice-route',action='store_true');a.add_argument('--human-report',type=Path);v=a.parse_args()
    prepare(v.copy_of_fast_start,v.model,v.voice_route,v.human_report)
