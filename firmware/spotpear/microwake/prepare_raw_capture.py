"""Prepare a COPY of 0.4.5. No install, capture, paid calls or KWS admission."""
import argparse,json,shutil
from pathlib import Path
from prepare_product import change
HERE=Path(__file__).resolve().parent

def prepare(root):
    main=root/'main'
    if '0.4.5-dev-fast-start-1' not in (root/'CMakeLists.txt').read_text():raise ValueError('Expected copy of installed fast-start baseline')
    if '#define GOBOT_WAKE_ROUTE 0' not in (main/'gobot_mww_config.h').read_text():raise ValueError('Do not change wake admission')
    for name in ('raw_wake_capture.h','gobot_raw_wake.h','gobot_raw_wake.cc'):shutil.copy2(HERE/name,main/name)
    change(main/'CMakeLists.txt','set(SOURCES "gobot_mww.cc"','set(SOURCES "gobot_raw_wake.cc" "gobot_mww.cc"')
    change(main/'CMakeLists.txt','                        esp_driver_uart','                        esp_driver_usb_serial_jtag\n                        esp_driver_uart')
    change(main/'audio/audio_service.cc','#include "gobot_duplex.h"','#include "gobot_duplex.h"\n#include "gobot_raw_wake.h"')
    change(main/'audio/audio_service.cc','gobot_mww::miss();vTaskDelay(pdMS_TO_TICKS(10));continue;',
        'gobot_raw_wake::missed_block();gobot_mww::miss();vTaskDelay(pdMS_TO_TICKS(10));continue;')
    change(main/'audio/audio_service.cc','if(local_hold_.load()) gobot_mww::retain(pcm.data(),pcm.size());',
        'gobot_raw_wake::feed(pcm.data(),pcm.size()); // Exact pre-AFE, pre-Opus KWS tap.\n            static bool raw_was_busy=false;\n            if(gobot_raw_wake::busy()){raw_was_busy=true;continue;}\n            if(raw_was_busy){gobot_mww::reset();raw_was_busy=false;}\n            if(local_hold_.load()) gobot_mww::retain(pcm.data(),pcm.size());')
    app=main/'application.cc'
    change(app,'#include "gobot_platform.h"','#include "gobot_platform.h"\n#include "gobot_raw_wake.h"')
    change(app,'    const auto phase=gobot_turn_.GetPhase();\n    if (hold) {',
        '    if(gobot_raw_wake::touch(physical,hold,now)){RenderGoBot();return;}\n    const auto phase=gobot_turn_.GetPhase();\n    if (hold) {')
    change(app,'    if(!audio_service_.LocalWakePending()) return;',
        '    if(!audio_service_.LocalWakePending()) return;\n    if(gobot_raw_wake::busy()){audio_service_.ClearLocalWake();return;}')
    change(app,'void Application::GoBotPoll() {',
        'void Application::GoBotPoll() {\n    gobot_raw_wake::poll(gobot::NowMs());')
    change(app,'void Application::GoBotSerial(const std::string& line) {',
        'void Application::GoBotSerial(const std::string& line) {\n    if(gobot_raw_wake::command(line,!gobot_turn_.Active() && audio_service_.IsPlaybackIdle(),gobot_muted_,gobot::NowMs())){RenderGoBot();return;}\n    if(gobot_raw_wake::busy())return;')
    change(app,'    touchui::Render(page);','    if(gobot_raw_wake::busy()){page.view=View::Notice;page.value=gobot_raw_wake::label();page.detail="Без облака";}\n    touchui::Render(page);')
    for p in (root/'CMakeLists.txt',main/'gobot_build_info.h'):
        change(p,'0.4.5-dev-fast-start-1','0.4.6-dev-raw-wake-1')
    (root/'raw-wake-manifest.json').write_text(json.dumps({'version':'0.4.6-dev-raw-wake-1',
        'capture_domain':'mono_pcm16_pre_afe','rate':16000,'maximum_seconds':60,
        'physical_touch_required':True,'default_recording':False,'standby_upload':False,
        'wake_route':False,'flashed':False},indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('copy_of_fast_start',type=Path);prepare(p.parse_args().copy_of_fast_start)
