"""Apply ONLY on a copy of the installed 0.4.3 media-ready source. Never flash.

Preserves its codec/AEC/touch/Brain transport. Known unqualified KWS stays local.
"""
import argparse,hashlib,json,shutil
from pathlib import Path
HERE=Path(__file__).resolve().parent

def replace(path,before,after):
    data=path.read_text()
    if data.count(before)!=1:raise ValueError(f'Unexpected baseline: {path.name}: {before[:60]}')
    path.write_text(data.replace(before,after))

def prepare(root):
    main=root/'main';cfg=(main/'gobot_mww_config.h').read_text()
    if '#define GOBOT_WAKE_ROUTE 0' not in cfg:raise ValueError('Diagnostic candidate must not open cloud sessions')
    if '0.4.3' not in (root/'CMakeLists.txt').read_text():raise ValueError('Expected installed media-ready 0.4.3 baseline')
    for name in ('gobot_mww.cc','gobot_mww.h','wake_question_buffer.h'):shutil.copy2(HERE/name,main/name)
    replace(main/'application.h','bool gobot_access_received_=false,',
        'bool gobot_wake_turn_=false;\n    bool gobot_access_received_=false,')
    replace(main/'application.cc','if(strcmp(source,"wake")) audio_service_.ClearLocalWake();',
        'gobot_wake_turn_ = !strcmp(source,"wake");\n    if(!gobot_wake_turn_) audio_service_.ClearLocalWake();')
    replace(main/'application.cc','void Application::GoBotPoll() {',
        'void Application::GoBotPoll() {\n    if(gobot_mww::consume_overflow() && gobot_wake_turn_ && gobot_turn_.Active()) {\n        GoBotFinish("wake_buffer_overflow");return;\n    }')
    replace(main/'audio/audio_service.cc','audio_input_need_warmup_ = true;',
        'audio_input_need_warmup_ = !local_hold_.load(); // Wake audio is already captured; retain first syllables.')
    replace(root/'CMakeLists.txt','0.4.3-dev-media-ready','0.4.4-dev-one-phrase-local')
    files=['gobot_mww.cc','gobot_mww.h','wake_question_buffer.h','application.cc','application.h','audio/audio_service.cc']
    report={'version':'0.4.4-dev-one-phrase-local','wake_route':False,'flashed':False,
        'buffer_seconds':12,'local_prefix_seconds':1,'human_verified':False,
        'files':{name:hashlib.sha256((main/name).read_bytes()).hexdigest() for name in files}}
    (root/'one-phrase-manifest.json').write_text(json.dumps(report,indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('copy_of_media_ready',type=Path);a=p.parse_args();prepare(a.copy_of_media_ready)
