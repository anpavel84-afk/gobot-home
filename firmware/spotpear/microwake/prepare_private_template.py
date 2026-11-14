"""Build only on COPY of installed raw0.4.6; PUBLIC placeholder, no flash."""
import argparse,hashlib,json,shutil
from pathlib import Path
from prepare_product import change
HERE=Path(__file__).resolve().parent
SLOT_BYTES=65536

def prepare(root):
    main=root/'main'
    if '0.4.6-dev-raw-wake-1' not in (root/'CMakeLists.txt').read_text():raise ValueError('Expected copy of installed raw0.4.6')
    if '#define GOBOT_WAKE_ROUTE 0' not in (main/'gobot_mww_config.h').read_text():raise ValueError('Template must remain local-only')
    blob=(HERE/'gobot.tflite').read_bytes()
    if hashlib.sha256(blob).hexdigest()!='1f3b425ba3dd977b30118513bce93f898b2e3a145235a1814b44249bc8183010':raise ValueError('Expected public synthetic-only placeholder')
    for name in ('gobot_mww.cc','gobot_mww.h','wake_question_buffer.h'):shutil.copy2(HERE/name,main/name)
    change(main/'gobot_mww.cc','if(++warm>=25 &&','if(++warm>=40 &&')
    (main/'gobot_mww.tflite').write_bytes(blob+bytes(SLOT_BYTES-len(blob)))
    change(main/'application.h','bool gobot_access_received_=false,','bool gobot_wake_turn_=false;\n    bool gobot_access_received_=false,')
    change(main/'application.cc','if(strcmp(source,"wake")) audio_service_.ClearLocalWake();','gobot_wake_turn_=!strcmp(source,"wake");\n    if(!gobot_wake_turn_)audio_service_.ClearLocalWake();')
    change(main/'application.cc','void Application::GoBotPoll() {','void Application::GoBotPoll() {\n    if(gobot_mww::consume_overflow() && gobot_wake_turn_ && gobot_turn_.Active()){GoBotFinish("wake_buffer_overflow");return;}')
    for path in (root/'CMakeLists.txt',main/'gobot_build_info.h'):change(path,'0.4.6-dev-raw-wake-1','0.4.7-dev-word-candidate-1')
    (root/'private-template-manifest.json').write_text(json.dumps({'version':'0.4.7-dev-word-candidate-1',
        'model_slot_bytes':SLOT_BYTES,'placeholder_sha256':hashlib.sha256((main/'gobot_mww.tflite').read_bytes()).hexdigest(),
        'warmup_invocations':40,'prefix_ms':1000,'buffer_ms':12000,'wake_route':False,
        'contains_personal_weights':False,'flashed':False},indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('copy_of_raw',type=Path);prepare(p.parse_args().copy_of_raw)
