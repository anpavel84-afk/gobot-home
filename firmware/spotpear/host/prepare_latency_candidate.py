"""Copy preserved 0.4.12 -> instrumented touch candidate. NEVER flash/deploy.
HOST client state is retained separately; this binary does not claim HOST ready.
"""
import argparse,hashlib,json,shutil
from pathlib import Path
HERE=Path(__file__).resolve().parent
VERSION='0.4.13-dev-touch-latency-1'

def prepare(source,dest):
    source=Path(source).resolve();dest=Path(dest).resolve()
    if dest.exists() or source==dest or source in dest.parents:raise ValueError('separate_new_candidate_path_required')
    if '0.4.12-dev-guided-calibration-1' not in (source/'CMakeLists.txt').read_text():raise ValueError('preserved_0412_required')
    model=(source/'main/gobot_mww.tflite').read_bytes()
    if hashlib.sha256(model[:60912]).hexdigest()!='4ffc532e16b3e20b7ce09099338023b5af304a0e31bf537034bb03dd67a4c5f9' or any(model[60912:]):raise ValueError('unexpected_local_model')
    shutil.copytree(source,dest,ignore=shutil.ignore_patterns('build','build-*','.git','__pycache__'))
    for name in ('host_client_state.h','latency_probe.h'):shutil.copy2(HERE/name,dest/'main'/name)
    def change(name,old,new):
        p=dest/name;s=p.read_text();
        if s.count(old)!=1:raise ValueError(f'anchor_mismatch:{name}:{old[:65]}')
        p.write_text(s.replace(old,new))
    change('CMakeLists.txt','0.4.12-dev-guided-calibration-1',VERSION)
    change('main/gobot_build_info.h','0.4.12-dev-guided-calibration-1',VERSION)
    change('main/protocols/protocol.h','    std::vector<uint8_t> payload;','    bool latency_remote_reply = false;\n    std::vector<uint8_t> payload;')
    change('main/protocols/protocol.h','    virtual bool Start() = 0;','    bool SendDiagnostic(const std::string& message) {return SendText(message);}\n    virtual bool Start() = 0;')
    change('main/protocols/websocket_protocol.cc','    cJSON_AddNumberToObject(root, "version", version_);','    cJSON_AddNumberToObject(root, "version", version_);\n    cJSON_AddBoolToObject(root,"latency_v1",true);')
    change('main/audio/audio_service.h','    uint32_t media_position_ms = 0;','    uint32_t media_position_ms = 0;\n    bool latency_remote_reply = false;')
    for name in ('main/audio/audio_service.cc','main/application.cc'):
        p=dest/name;p.write_text('#include "latency_probe.h"\n'+p.read_text())
    change('main/audio/audio_service.cc','        frame_level_=data.empty()?0:total/data.size();','        frame_level_=data.empty()?0:total/data.size();\n        gobot_latency::probe().Mic(voice_detected_.load(),esp_timer_get_time());')
    change('main/audio/audio_service.cc','            task.media_position_ms = packet->media_position_ms;','            task.media_position_ms = packet->media_position_ms;\n            task.latency_remote_reply = packet->latency_remote_reply;')
    change('main/audio/audio_service.cc','        codec_->OutputData(task.pcm);','        if(task.latency_remote_reply)gobot_latency::probe().WriteEnter(esp_timer_get_time());\n        codec_->OutputData(task.pcm);\n        if(task.latency_remote_reply)gobot_latency::probe().WriteReturn(esp_timer_get_time());')
    change('main/application.cc','        if (GetDeviceState() == kDeviceStateSpeaking) {\n            audio_service_.PushPacketToDecodeQueue(std::move(packet));','        if (GetDeviceState() == kDeviceStateSpeaking) {\n            packet->latency_remote_reply=true;\n            gobot_latency::probe().Packet(esp_timer_get_time());\n            audio_service_.PushPacketToDecodeQueue(std::move(packet));')
    change('main/application.cc','    if (gobot_muted_ || gobot_turn_.Active()) return;\n    gobot_wake_turn_','    if (gobot_muted_ || gobot_turn_.Active()) return;\n    gobot_latency::probe().Begin(esp_timer_get_time());\n    gobot_wake_turn_')
    change('main/application.cc','void Application::EndTouchCapture() {','void Application::EndTouchCapture() {\n    gobot_latency::probe().End(esp_timer_get_time());')
    change('main/application.cc','            if (audio_service_.IsPlaybackIdle()) {\n                notify_player_','            if (audio_service_.IsPlaybackIdle()) {\n                gobot_latency::probe().TasksDrained(esp_timer_get_time());\n                notify_player_')
    handler='''        if(!strcmp(type->valuestring,"gobot_latency_ready")) {
            const auto trace=gobot::String(root,"trace_id",64);
            const auto session=gobot::String(root,"session_id",64);
            const auto kind=gobot::String(root,"audio_kind",32);
            if(trace && session && kind) Schedule([this,t=std::string(trace),s=std::string(session),k=std::string(kind)](){
                if(!protocol_ || protocol_->session_id()!=s)return;
                // A boot-local monotonic clock domain, never a wall-clock estimate.
                static const std::string clock=[](){char b[33];snprintf(b,sizeof(b),"%08lx%08lx%08lx%08lx",(unsigned long)esp_random(),(unsigned long)esp_random(),(unsigned long)esp_random(),(unsigned long)esp_random());return std::string(b);}();
                gobot_latency::probe().Bind(t,s,clock,k);
            });
            return;
        }
'''
    change('main/application.cc','        if(!strcmp(type->valuestring,"gobot_input_end")) {',handler+'        if(!strcmp(type->valuestring,"gobot_input_end")) {')
    p=dest/'main/application.cc';p.write_text('#include <esp_random.h>\n'+p.read_text())
    change('main/application.cc','void Application::GoBotPoll() {','''void Application::GoBotPoll() {
    if(protocol_ && protocol_->IsAudioChannelOpened()) {
        for(unsigned n=0;n<10;++n) {
            auto message=gobot_latency::probe().Next(protocol_->session_id());
            if(message.empty())break;
            if(!protocol_->SendDiagnostic(message))break;
        }
    }
''')
    report={'version':VERSION,'source_version':'0.4.12-dev-guided-calibration-1',
      'latency_probe':True,'first_reply_only':True,'host_client_complete':False,
      'acoustic_playback_start_measured':False,'output_landmarks':'driver function entry/return and software tasks drain; not acoustic truth',
      'default_wake_route_changed':False,'model_changed':False,'firmware_flashed':False,
      'runtime_switched':False,'paid_calls':0,
      'changes':{str(p.relative_to(dest)):hashlib.sha256(p.read_bytes()).hexdigest() for p in dest.glob('main/**/latency_probe.h')}}
    (dest/'latency-candidate.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('source');p.add_argument('destination');a=p.parse_args();prepare(a.source,a.destination)
