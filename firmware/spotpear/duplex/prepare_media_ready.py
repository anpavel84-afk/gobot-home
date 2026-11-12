"""Start touch capture after transport readiness, never replay a whole setup backlog."""
from pathlib import Path
from prepare_duplex import change

def prepare(root):
    m=root/'main'
    for p in (root/'CMakeLists.txt',m/'gobot_build_info.h'):
        change(p,'0.4.2-dev-session-ack','0.4.3-dev-media-ready')
    p=m/'application.h'
    marker='    bool live_continuous_=false;uint64_t activity_reported_=0;'
    change(p,marker,marker+'\n    bool gobot_access_received_=false,gobot_media_ready_=false,gobot_listen_announced_=false,gobot_limit_end_=false;')
    p=m/'protocols/protocol.h'
    change(p,'\\"continuous\\":true}', '\\"continuous\\":true,\\"capture_deferred\\":true}')
    p=m/'application.cc'
    marker='        if (!strcmp(type->valuestring,"gobot_access")) {'
    extra='''        if (!strcmp(type->valuestring,"gobot_media_ready") || !strcmp(type->valuestring,"gobot_session_end")) {
            auto ident=gobot::String(root,"session_id",80);
            auto reason=gobot::String(root,"reason",32);
            const bool ready=!strcmp(type->valuestring,"gobot_media_ready");
            if(ident) Schedule([this,id=std::string(ident),ready,limit=reason && !strcmp(reason,"session_time_limit")](){
                if(!protocol_ || protocol_->session_id()!=id || !gobot_turn_.Active() || !live_continuous_)return;
                if(!ready){gobot_limit_end_=limit;return;}
                if(!gobot_access_received_ || gobot_media_ready_)return;
                gobot_media_ready_=true;
                ESP_LOGI(TAG,"GOBOT_MEDIA_READY phase=%d",int(gobot_turn_.GetPhase()));
                StartListeningAudio();RenderGoBot();
            });
            return;
        }
'''
    change(p,marker,extra+marker)
    marker='                live_continuous_=ok && full;gobot_turn_.Continuous(live_continuous_);'
    change(p,marker,marker+'\n                gobot_access_received_=ok;\n                if(ok && !full){gobot_media_ready_=true;StartListeningAudio();}')
    marker='    if (GetDeviceState()!=kDeviceStateIdle || !gobot_turn_.Begin(gobot::NowMs())) return;'
    change(p,marker,marker+'\n    gobot_access_received_=gobot_media_ready_=gobot_listen_announced_=gobot_limit_end_=false;')
    change(p,'    case gobot::Phase::Capturing:page.view=View::Listening;break;',
           '    case gobot::Phase::Capturing:page.view=(!gobot_access_received_ || (live_continuous_ && !gobot_media_ready_))?View::Connecting:View::Listening;break;')
    change(p,'    protocol_->SendStartListening(listening_mode_);\n    audio_service_.EnableVoiceProcessing(true);',
           '    if(!gobot_listen_announced_){protocol_->SendStartListening(listening_mode_);gobot_listen_announced_=true;}\n    if(!gobot_access_received_ || (live_continuous_ && !gobot_media_ready_)) return;\n    audio_service_.EnableVoiceProcessing(true);')
    marker='    reported_playing_=false;local_pause_active_=false;duplex_started_=0;live_continuous_=false;gobot_turn_.Continuous(false);'
    change(p,marker,'''    if(gobot_limit_end_){notice_="Минута завершена";notice_until_=gobot::NowMs()+4500;}
    gobot_access_received_=gobot_media_ready_=gobot_listen_announced_=gobot_limit_end_=false;
'''+marker)

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('tree',type=Path)
    prepare(parser.parse_args().tree)
