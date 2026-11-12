"""Continuous C overlay. Provider controls conversation turns; local silence never commits."""
from pathlib import Path
from prepare_duplex import change
def prepare(root):
    m=root/"main";a=m/"application.cc";h=m/"gobot_turn_guard.h"
    change(root/"CMakeLists.txt","0.4.0-dev-duplex","0.4.1-dev-livekit")
    change(m/"gobot_build_info.h","0.4.0-dev-duplex","0.4.1-dev-livekit")
    change(h,'    bool Begin(uint64_t now) {','    void Continuous(bool enabled){continuous_=enabled;}\n    bool Begin(uint64_t now) {')
    change(h,'        if (phase_ != Phase::Waiting) return false;','        if (phase_ != Phase::Waiting && !(continuous_ && phase_==Phase::Capturing)) return false;')
    change(h,'        phase_ = Phase::Draining; since_ = now; return true;','        phase_ = continuous_?Phase::Capturing:Phase::Draining; since_ = now; return true;')
    change(h,'        switch (phase_) {','        if(continuous_ && Active() && phase_!=Phase::Connecting)return Action::None;\n        switch (phase_) {')
    change(h,'    bool UploadAllowed() const { return phase_ == Phase::Capturing; }','    bool UploadAllowed() const { return phase_==Phase::Capturing || (continuous_ && Active() && phase_!=Phase::Connecting); }')
    change(h,'    Phase phase_ = Phase::Idle;','    bool continuous_=false;\n    Phase phase_ = Phase::Idle;')
    change(m/"application.h",'    bool duplex_armed_=false;','    bool live_continuous_=false;uint64_t activity_reported_=0;\n    bool duplex_armed_=false;')
    change(a,'            auto clock=cJSON_GetObjectItem(root,"idle_clock");','            auto continuous=cJSON_GetObjectItem(root,"continuous");\n            const bool full=cJSON_IsTrue(continuous);\n            auto clock=cJSON_GetObjectItem(root,"idle_clock");')
    change(a,'Schedule([this,id=std::string(session),limit=','Schedule([this,full,id=std::string(session),limit=')
    change(a,'                if(!ok){GoBotFinish("voice_gate");','                live_continuous_=ok && full;gobot_turn_.Continuous(live_continuous_);\n                if(!ok){GoBotFinish("voice_gate");')
    change(a,'            if (listening_mode_ != kListeningModeRealtime) {','            if (!live_continuous_ && listening_mode_ != kListeningModeRealtime) {')
    change(a,'            audio_service_.ResetDecoder();\n            break;\n        case kDeviceStateNotifying:',
        '            if(!live_continuous_) audio_service_.ResetDecoder();\n            break;\n        case kDeviceStateNotifying:')
    change(a,'if(!local_pause_active_ && protocol_ && protocol_->session_id()==id && gobot_turn_.Submit(true))',
        'if(!live_continuous_ && !local_pause_active_ && protocol_ && protocol_->session_id()==id && gobot_turn_.Submit(true))')
    change(a,'    reported_playing_=false;local_pause_active_=false;duplex_started_=0;',
        '    reported_playing_=false;local_pause_active_=false;duplex_started_=0;live_continuous_=false;gobot_turn_.Continuous(false);')
    change(a,'    if(playing!=reported_playing_ && protocol_ && protocol_->IsAudioChannelOpened()){',
        '    if((playing!=reported_playing_ || (live_continuous_ && now>=activity_reported_+300)) && protocol_ && protocol_->IsAudioChannelOpened()){')
    change(a,'        protocol_->SendPlaybackActivity(playing);reported_playing_=playing;',
        '        protocol_->SendPlaybackActivity(playing,live_continuous_ && audio_service_.IsVoiceDetected());reported_playing_=playing;activity_reported_=now;')
    protocol=m/"protocols/protocol.h"
    change(protocol,'void SendPlaybackActivity(bool playing) {','void SendPlaybackActivity(bool playing,bool input_active=false) {')
    change(protocol,'+(playing?"true}":"false}"));',
        '+(playing?"true":"false")+",\\"input_active\\":"+(input_active?"true}":"false}"));')
    change(a,'    audio_service_.EnableVoiceProcessing(true);\n\n    ConfigureWakeWordForListening();',
        '    audio_service_.EnableVoiceProcessing(true);\n    audio_service_.EnableDeviceAec(true);\n\n    ConfigureWakeWordForListening();')
    change(a,'    if(duplex_started_){','    if(live_continuous_ && gobot::NowMs()>touch_started_+180000){GoBotFinish("session_lifetime");return;}\n    if(duplex_started_){')
    # Local diagnostics must never be reported as network upload.
    change(a,'static_cast<unsigned>(words.size()),gobot_turn_.UploadAllowed());','static_cast<unsigned>(words.size()),!local_pause_active_ && gobot_turn_.UploadAllowed());')
if __name__=="__main__":
    import argparse
    p=argparse.ArgumentParser();p.add_argument("tree",type=Path);prepare(p.parse_args().tree)
