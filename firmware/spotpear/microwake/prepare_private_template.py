"""Build only on COPY of installed raw0.4.6; PUBLIC placeholder, no flash."""
import argparse,hashlib,json,shutil
from pathlib import Path
from prepare_product import change
HERE=Path(__file__).resolve().parent
SLOT_BYTES=65536

def prepare(root,reference=False):
    main=root/'main'
    slot_bytes=131072 if reference else SLOT_BYTES
    warmup,window,cutoff=(68,10,231) if reference else (40,3,250)
    version='0.4.8-dev-reference-local-1' if reference else '0.4.7-dev-word-candidate-1'
    if '0.4.6-dev-raw-wake-1' not in (root/'CMakeLists.txt').read_text():raise ValueError('Expected copy of installed raw0.4.6')
    if '#define GOBOT_WAKE_ROUTE 0' not in (main/'gobot_mww_config.h').read_text():raise ValueError('Template must remain local-only')
    blob=(HERE/'gobot.tflite').read_bytes()
    if hashlib.sha256(blob).hexdigest()!='1f3b425ba3dd977b30118513bce93f898b2e3a145235a1814b44249bc8183010':raise ValueError('Expected public synthetic-only placeholder')
    for name in ('gobot_mww.cc','gobot_mww.h','wake_question_buffer.h','probability_window.h'):shutil.copy2(HERE/name,main/name)
    config=main/'gobot_mww_config.h'
    change(config,'#define GOBOT_WAKE_CUTOFF 250',f'#define GOBOT_WAKE_CUTOFF {cutoff}')
    with config.open('a') as output:output.write(f'\n#define GOBOT_WAKE_WINDOW {window}\n#define GOBOT_WAKE_WARMUP {warmup}\n')
    if reference:
        source=main/'gobot_mww.cc'
        change(source,'MicroMutableOpResolver<13>','MicroMutableOpResolver<15>')
        change(source,'ops.AddAveragePool2D()!=kTfLiteOk','ops.AddSplit()!=kTfLiteOk || ops.AddSplitV()!=kTfLiteOk || ops.AddAveragePool2D()!=kTfLiteOk')
        change(source,'arena_size=128*1024','arena_size=512*1024')
        change(source,'heap_caps_aligned_alloc(16,2048,caps)','heap_caps_aligned_alloc(16,4096,caps)')
        change(source,'MicroAllocator::Create(var_memory,2048)','MicroAllocator::Create(var_memory,4096)')
        change(source,'MicroResourceVariables::Create(allocator,20)','MicroResourceVariables::Create(allocator,32)')
    (main/'gobot_mww.tflite').write_bytes(blob+bytes(slot_bytes-len(blob)))
    change(main/'application.cc','#include "application.h"','#include "application.h"\n#include "gobot_mww.h"')
    change(main/'application.h','bool gobot_access_received_=false,','bool gobot_wake_turn_=false;\n    bool gobot_access_received_=false,')
    change(main/'application.cc','if(strcmp(source,"wake")) audio_service_.ClearLocalWake();','gobot_wake_turn_=!strcmp(source,"wake");\n    if(!gobot_wake_turn_)audio_service_.ClearLocalWake();')
    change(main/'application.cc','void Application::GoBotPoll() {','void Application::GoBotPoll() {\n    if(gobot_mww::consume_overflow() && gobot_wake_turn_ && gobot_turn_.Active()){GoBotFinish("wake_buffer_overflow");return;}')
    change(main/'audio/audio_service.h','    void SetLocalScan(bool on);','    bool IsLocalScanRunning() const;\n    void SetLocalScan(bool on);')
    change(main/'audio/audio_service.cc','void AudioService::SetLocalScan(bool on) {','bool AudioService::IsLocalScanRunning() const {return xEventGroupGetBits(event_group_) & kLocalScan;}\nvoid AudioService::SetLocalScan(bool on) {')
    change(main/'application.cc','static_cast<int>(gobot_turn_.GetPhase()),audio_service_.IsWakeWordRunning(),',
        'static_cast<int>(gobot_turn_.GetPhase()),audio_service_.IsLocalScanRunning() && gobot_mww::ready(),')
    change(main/'application.cc','    touchui::Render(page);','    if(page.view==View::Ready && !gobot_muted_ && gobot_mww::qualified() && gobot_mww::ready() && audio_service_.IsLocalScanRunning())page.detail="Скажите ГоБот";\n    touchui::Render(page);')
    change(main/'touch_screen.h','            text("Коснитесь, чтобы",168,atlas::muted);\n            text("говорить",187,atlas::muted);',
        '            if(!p.detail.empty())text(p.detail,168,atlas::muted,1,184);\n            else {text("Коснитесь, чтобы",168,atlas::muted);text("говорить",187,atlas::muted);}')
    for path in (root/'CMakeLists.txt',main/'gobot_build_info.h'):change(path,'0.4.6-dev-raw-wake-1',version)
    (root/'private-template-manifest.json').write_text(json.dumps({'version':version,
        'model_slot_bytes':slot_bytes,'placeholder_sha256':hashlib.sha256((main/'gobot_mww.tflite').read_bytes()).hexdigest(),
        'warmup_invocations':warmup,'probability_window':window,'cutoff':cutoff,'prefix_ms':1000,'buffer_ms':12000,'wake_route':False,
        'contains_personal_weights':False,'flashed':False},indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('copy_of_raw',type=Path);p.add_argument('--reference',action='store_true');a=p.parse_args();prepare(a.copy_of_raw,a.reference)
