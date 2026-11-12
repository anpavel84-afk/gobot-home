void Application::TouchGesture(bool physical, bool hold) {
    const uint64_t now=gobot::NowMs();
    if (physical) ++touch_events_;
    if (now < last_contact_+350) return;
    last_contact_=now;
    const auto phase=gobot_turn_.GetPhase();
    if (hold) {
        if (gobot_turn_.Active()) {
            if(protocol_ && protocol_->IsAudioChannelOpened()) protocol_->SendAbortSpeaking(kAbortReasonNone);
            GoBotFinish("manual_stop");
        } else {
            gobot_muted_=!gobot_muted_;
            Settings("gobot_ui",true).SetInt("muted",gobot_muted_?1:0);
        }
    } else if (gobot_muted_) {
        ESP_LOGI(TAG,"GOBOT_ACTIVATION_REJECT reason=muted");
    } else if (phase==gobot::Phase::Capturing) {
        if (gobot_turn_.Submit(audio_service_.IsVoiceDetected())) EndTouchCapture();
        else GoBotFinish("empty_capture");
    } else if (phase==gobot::Phase::Idle) {
        if(timer_latched_) {timer_latched_=false; timer_key_.clear();}
        else StartGoBotTurn(physical?"touch":"button");
    }
    RenderGoBot();
}

void Application::StartGoBotTurn(const char* source) {
    gobot::Enrollment enrollment;
    if (gobot_muted_ || gobot_turn_.Active()) return;
    if (!gobot_network_ready_ || !gobot::LoadEnrollment(enrollment) || !protocol_) {
        notice_=gobot_network_ready_?"Нужна регистрация":"Нет Wi-Fi";
        notice_until_=gobot::NowMs()+4200;
        return;
    }
    if (GetDeviceState()!=kDeviceStateIdle || !gobot_turn_.Begin(gobot::NowMs())) return;
    ++activation_count_;
    notice_until_=0; weather_until_=0;
    ESP_LOGI(TAG,"GOBOT_ACTIVATION source=%s number=%u",source,activation_count_);
    if (!SetDeviceState(kDeviceStateConnecting)) {GoBotFinish("connect_failed");return;}
    RenderGoBot();
    Schedule([this,generation=gobot_turn_.Generation()](){
        if(generation==gobot_turn_.Generation() && gobot_turn_.GetPhase()==gobot::Phase::Connecting)
            ContinueWakeWordInvoke("");
    });
}

void Application::EndTouchCapture() {
    audio_service_.EnableVoiceProcessing(false);
    while(auto packet=audio_service_.PopPacketFromSendQueue()) {
        if(protocol_ && protocol_->IsAudioChannelOpened()) protocol_->SendAudio(std::move(packet));
    }
    if(protocol_) protocol_->SendStopListening();
    ESP_LOGI(TAG,"GOBOT_UTTERANCE_END upload=0");
}

void Application::RenderGoBot() {
    using touchui::View;
    touchui::Page page;
    page.skin=skin_;
    const auto now=gobot::NowMs();
    char counter[24]={};
    if (gobot_timer_end_) {
        const int seconds=now<gobot_timer_end_?(gobot_timer_end_-now+999)/1000:0;
        snprintf(counter,sizeof(counter),"%d:%02d",seconds/60,seconds%60);
        if (!seconds) {gobot_timer_end_=0;timer_latched_=true;}
    }
    if (timer_latched_ || gobot_timer_end_) page.badge=timer_latched_?"Время вышло":counter;
    if(gobot_muted_) page.view=View::Muted;
    else if(!gobot_network_ready_) page.view=View::Offline;
    else switch(gobot_turn_.GetPhase()) {
    case gobot::Phase::Connecting:page.view=View::Connecting;break;
    case gobot::Phase::Capturing:page.view=View::Listening;break;
    case gobot::Phase::Waiting:page.view=View::Thinking;break;
    case gobot::Phase::Speaking:
    case gobot::Phase::Draining:
        page.view=View::Speaking;
        page.mouth=!audio_service_.IsPlaybackIdle() && (now/240)%2;
        break;
    default:page.view=View::Ready;
    }
    if (page.view==View::Ready && notice_until_>now) {
        page.view=View::Notice;page.value=notice_;page.detail=notice_=="Лимит Live исчерпан"?"Нужен новый лимит":"Повторить касанием";
    } else if (page.view==View::Ready && (timer_latched_ || gobot_timer_end_)) {
        page.view=View::Timer;page.value=timer_latched_?"0:00":counter;
        page.detail=timer_latched_?"Время вышло":"Таймер";
    } else if ((page.view==View::Ready || page.view==View::Speaking) && weather_until_>now) {
        page.view=View::Weather;page.icon=weather_icon_;page.value=weather_value_;page.detail=weather_detail_;
    } else if (page.view==View::Ready && idle_clock_ && now>last_contact_+30000) {
        time_t t=time(nullptr); struct tm local{};
        if(localtime_r(&t,&local) && local.tm_year>=125) {
            char clock[12]; strftime(clock,sizeof(clock),"%H:%M",&local);
            page.view=View::Clock;page.value=clock;page.detail="Коснитесь для разговора";
        }
    }
    const bool playing=(gobot_turn_.GetPhase()==gobot::Phase::Speaking || gobot_turn_.GetPhase()==gobot::Phase::Draining) && !audio_service_.IsPlaybackIdle();
    if(playing!=reported_playing_ && protocol_ && protocol_->IsAudioChannelOpened()){
        protocol_->SendPlaybackActivity(playing);reported_playing_=playing;
    }
    touchui::Render(page);
}
