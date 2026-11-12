"""Apply the touch release to an isolated, prepared 0.1.1 display checkout."""
import sys
from pathlib import Path
from shutil import copyfile

root=Path(sys.argv[1]).resolve()
here=Path(__file__).resolve().parent
def edit(file, old, new, expected=1):
    p=root/file
    s=p.read_text()
    if s.count(old)!=expected:
        raise ValueError(f"Unexpected base in {file}: {old[:60]}")
    p.write_text(s.replace(old,new))

cpp="main/application.cc"
header="main/application.h"
for file in ("CMakeLists.txt","main/gobot_build_info.h"):
    edit(file,'"0.1.1-dev-display"','"0.2.3-dev-touch-auto"')
atlas=Path(sys.argv[2]) if len(sys.argv)>2 else here/"touch_atlas.h"
copyfile(atlas,root/"main/touch_atlas.h")
for name in ("touch_lcd.h","touch_screen.h"):
    copyfile(here/name,root/"main"/name)
# The upstream AFE initialization aborts voice capture if the optional MultiNet
# self-test fails. Touch firmware uses AFE/VAD only; do not instantiate a KWS engine.
edit("main/audio/engines/afe_audio_engine.cc",
     "if (multinet_model_name != nullptr) {",
     "constexpr bool touch_only = true;\n    if (!touch_only && multinet_model_name != nullptr) {")
edit("main/audio/engines/afe_audio_engine.cc",
     "} else if (wakenet_model_name != nullptr) {",
     "} else if (!touch_only && wakenet_model_name != nullptr) {")
edit("main/audio/audio_service.h","    bool voice_detected_ = false;","    std::atomic<bool> voice_detected_{false};\n    std::atomic<uint32_t> frame_level_{0};")
edit("main/audio/audio_service.h","    bool IsVoiceDetected()", "    uint32_t FrameLevel() const {return frame_level_.load();}\n    bool IsVoiceDetected()")
edit("main/audio/audio_service.cc","        PushTaskToEncodeQueue(kAudioTaskTypeEncodeToSendQueue, std::move(data));",
     """        uint32_t total=0;
        for(int16_t sample:data) total+=std::abs(static_cast<int>(sample));
        frame_level_=data.empty()?0:total/data.size();
        PushTaskToEncodeQueue(kAudioTaskTypeEncodeToSendQueue, std::move(data));""")
edit("main/audio/audio_service.cc","        audio_engine_->EnableVoiceProcessing(true);","        frame_level_=0;voice_detected_=false;\n        audio_engine_->EnableVoiceProcessing(true);")
edit(cpp,'                if(!gobot_turn_.UploadAllowed()) continue;',
     '                if(local_pause_active_ || !gobot_turn_.UploadAllowed()) continue;')
edit(cpp,'#include "gobot_scene.h"','#include "gobot_scene.h"\n#include "touch_lcd.h"')
edit(header,"    AudioService& GetAudioService()", "    void TouchGesture(bool physical, bool hold);\n    AudioService& GetAudioService()")
edit(header,"    void GoBotPoll();",'''    void GoBotPoll();
    void RenderGoBot();
    void EndTouchCapture();
    void StartGoBotTurn(const char*);
    uint64_t last_contact_=0, notice_until_=0, weather_until_=0;
    unsigned touch_events_=0, activation_count_=0;
    bool reported_playing_=false, local_pause_armed_=false, local_pause_active_=false;
    unsigned auto_ends_=0; uint64_t touch_started_=0;
    uint32_t peak_level_=0;
    int skin_=0, weather_icon_=0;
    bool timer_latched_=false, idle_clock_=false;
    std::string notice_,timer_key_,weather_value_,weather_detail_;''')
edit("main/gobot_turn_guard.h","    bool TtsStart",'''    bool Submit(bool voice) {
        if (phase_ != Phase::Capturing || (!heard_voice_ && !voice)) return false;
        phase_=Phase::Waiting;
        since_=last_voice_;
        return true;
    }
    bool TtsStart''')
edit(cpp,'    startup_completed_=true;', '''    { Settings settings("gobot_ui",false);
      skin_=std::clamp<int>(settings.GetInt("skin",0),0,2);
      idle_clock_=settings.GetInt("clock",0);
      gobot_muted_=settings.GetInt("muted",0); }
    startup_completed_=true;''')
p=root/cpp;s=p.read_text()
a=s.index("void Application::HandleToggleChatEvent()")
b=s.index("void Application::ContinueOpenAudioChannel",a)
s=s[:a]+(here/"touch_methods.inc").read_text()+'\nvoid Application::HandleToggleChatEvent() { TouchGesture(false,false); }\n\n'+s[b:]
a=s.index("void Application::HandleWakeWordDetectedEvent()")
b=s.index("void Application::BeginWakeWordInvoke",a)
s=s[:a]+'void Application::HandleWakeWordDetectedEvent() { /* Touch release: KWS is not armed. */ }\n\n'+s[b:]
a=s.index("    if (gobot_timer_end_)",s.index("void Application::GoBotPoll()"))
b=s.index("    switch(gobot_turn_",a)
s=s[:a]+'    RenderGoBot();\n'+s[b:]
a=s.index("        audio_service_.EnableVoiceProcessing(false);",s.index("case gobot::Action::StopCapture:"))
b=s.index("break;",a)
s=s[:a]+"        EndTouchCapture(); "+s[b:]
# No startup hint or KWS worker in touch-only standby.
s=s.replace("EnableWakeWordDetection(!gobot_muted_)","EnableWakeWordDetection(false)").replace("EnableWakeWordDetection(audio_service_.IsAfeWakeWord())","EnableWakeWordDetection(false)")
s=s.replace("Скажите: ГоБот","Коснитесь, чтобы говорить").replace("ГоБот: требуется калибровка","Коснитесь, чтобы говорить")
s=s.replace('play_popup_on_listening_ = true;', 'play_popup_on_listening_ = false;')
p.write_text(s)
edit(cpp,'    switch(gobot_turn_.Poll(gobot::NowMs(),audio_service_.IsVoiceDetected(),audio_service_.IsPlaybackIdle())) {', '''    bool speech=audio_service_.IsVoiceDetected();
    if(gobot_turn_.GetPhase()==gobot::Phase::Capturing) {
        const uint32_t level=audio_service_.FrameLevel();
        if(speech) peak_level_=std::max(peak_level_,level);
        // AFE may keep VAD open on room noise after speech. A sustained quiet
        // tail still goes through the normal 800ms hangover; never gate the uplink.
        if(peak_level_>=240 && level<80 && level*8<peak_level_) speech=false;
    }
    switch(gobot_turn_.Poll(gobot::NowMs(),speech,audio_service_.IsPlaybackIdle())) {''')
edit(cpp,'    last_error_message_.clear();\n    SetDeviceState(kDeviceStateIdle);','''    if (!strcmp(reason,"connect_failed") || !strcmp(reason,"network_error") || !strcmp(reason,"timeout")) {
        notice_="Связь прервана";notice_until_=gobot::NowMs()+4500;
    }
    reported_playing_=false;local_pause_active_=false;
    last_error_message_.clear();
    SetDeviceState(kDeviceStateIdle);''')
edit(cpp,'                gobot_timer_end_ = scene.remaining_ms >= 0 ? gobot::NowMs() + scene.remaining_ms : 0;', '''                if (scene.remaining_ms>=0 && !scene.key.empty() && timer_key_!=scene.key) {
                    timer_key_=scene.key; timer_latched_=false;gobot_timer_end_=gobot::NowMs()+scene.remaining_ms;
                }
                if(scene.weather>=0) {
                    weather_icon_=scene.weather;weather_value_=scene.title;weather_detail_=scene.text;
                    weather_until_=gobot::NowMs()+14000;
                }''')
edit("main/gobot_scene.h","    int remaining_ms = -1;","    int remaining_ms = -1, weather=-1;\n    std::string key;")
edit("main/gobot_scene.h","    scene.title = title;",'''    if(auto key=String(root,"timer_key",120)) scene.key=key;
    if(auto icon=String(root,"weather_icon",20)) {
        const char* icons[]={"sun","partly_cloudy","cloud","rain","snow","storm"};
        for(int i=0;i<6;i++) if(!strcmp(icon,icons[i])) scene.weather=i;
        if(scene.weather<0) scene.weather=2;
    }
    scene.title = title;''')
edit(cpp,'        // No remote OTA', '''        if(!strcmp(type->valuestring,"gobot_input_end")) {
            auto ident=gobot::String(root,"session_id",80);
            if(ident) Schedule([this,id=std::string(ident)](){
                if(!local_pause_active_ && protocol_ && protocol_->session_id()==id && gobot_turn_.Submit(true)) EndTouchCapture();
            });
            return;
        }
        if (!strcmp(type->valuestring,"gobot_access")) {
            auto session=gobot::String(root,"session_id",80);
            auto allowed=cJSON_GetObjectItem(root,"allowed");
            if(!session || !cJSON_IsBool(allowed)) return;
            auto reason=gobot::String(root,"reason",24);
            auto selected=gobot::String(root,"skin",12);
            auto clock=cJSON_GetObjectItem(root,"idle_clock");
            Schedule([this,id=std::string(session),limit=reason && !strcmp(reason,"hardware_voice_limit"),ok=bool(cJSON_IsTrue(allowed)),skin=std::string(selected?selected:""),clockMode=cJSON_IsBool(clock)?int(cJSON_IsTrue(clock)):-1](){
                if(!protocol_ || protocol_->session_id()!=id || !gobot_turn_.Active()) return;
                int index=skin=="minimal"?2:skin=="soft"?1:skin=="classic"?0:-1;
                if(index>=0 && skin_!=index){skin_=index;Settings("gobot_ui",true).SetInt("skin",index);}
                if(clockMode>=0 && idle_clock_!=bool(clockMode)){idle_clock_=clockMode;Settings("gobot_ui",true).SetInt("clock",clockMode);}
                if(!ok){GoBotFinish("voice_gate");notice_=limit?"Лимит Live исчерпан":"Нужен допуск Live";notice_until_=gobot::NowMs()+5000;RenderGoBot();}
            });
            return;
        }
        // No remote OTA''')
edit(cpp,'    } else if(line=="GOBOT_STATUS") {','''    } else if(line.rfind("GOBOT_VOLUME ",0)==0 && !gobot_turn_.Active()) {
        auto codec=Board::GetInstance().GetAudioCodec();
        std::string value=line.substr(13);
        if(codec && !value.empty() && value.size()<=3 && value.find_first_not_of("0123456789")==std::string::npos) {
            int percent=atoi(value.c_str());
            if(percent>=10 && percent<=100) codec->SetOutputVolume(percent);
        }
    } else if(line=="GOBOT_CHECK_PAUSE" && !gobot_turn_.Active() && !gobot_muted_) {
        local_pause_armed_=true;notice_="Проверка паузы";notice_until_=gobot::NowMs()+30000;
        ESP_LOGI(TAG,"GOBOT_PAUSE_CHECK armed=1");RenderGoBot();
    } else if(line=="GOBOT_SOUND_CHECK" && !gobot_turn_.Active()) {
        audio_service_.PlaySound(Lang::Sounds::OGG_POPUP);
        ESP_LOGI(TAG,"GOBOT_SOUND_CHECK local=1");
    } else if(line=="GOBOT_STATUS") {
        ESP_LOGI(TAG,"GOBOT_ENDPOINT auto_ends=%u local=%d",auto_ends_,local_pause_active_);\n        ESP_LOGI(TAG,"GOBOT_VOLUME percent=%d",Board::GetInstance().GetAudioCodec()->output_volume());''')
edit(cpp,'        const auto words=audio_service_.GetWakeWords();', '''        ESP_LOGI(TAG,"GOBOT_TOUCH_STATUS events=%u activations=%u",touch_events_,activation_count_);
        const auto words=audio_service_.GetWakeWords();''')
f="main/boards/spotpear/sp-esp32-s3-1.28-box/sp-esp32-s3-1.28-box.cc"
p=root/f;s=p.read_text()
a=s.index("            if (touch_duration < TOUCH_THRESHOLD_MS)");b=s.index("\n        }",a)
s=s[:a]+'''            if (touch_duration >= 40 && touch_duration <= 3000) {
                const bool hold=touch_duration>=650;
                auto& app=Application::GetInstance();
                app.Schedule([hold](){Application::GetInstance().TouchGesture(true,hold);});
            }'''+s[b:]
p.write_text(s)
edit("main/protocols/protocol.h","    virtual void SendStartListening",'''    void SendPlaybackActivity(bool playing) {
        SendText(std::string("{\\"session_id\\":\\"")+session_id_+"\\",\\"type\\":\\"gobot_activity\\",\\"playing\\":"+(playing?"true}":"false}"));
    }
    virtual void SendStartListening''')
