// HOST-A RC1: opt-in, volatile, isolated test transport. Included by application.cc.
// No additional Brain, recorder, paid cloud listener, or permanent task is created.
// All calls here execute on the existing Application main task.
void Application::HostControl(const std::string& type,const std::string& extra) {
    auto* ws=static_cast<WebsocketProtocol*>(protocol_.get());
    if(!ws || !host_ready_ || !ws->IsAudioChannelOpened())return;
    const auto json=std::string("{\"type\":\"")+type+
        "\",\"session_id\":\""+ws->HostSession()+
        "\",\"epoch\":\""+ws->HostEpoch()+"\""+extra+"}";
    if(!ws->HostSend(json))HostFault("send_failed");
}

void Application::HostFault(const char* reason) {
    ESP_LOGE(TAG,"GOBOT_HOST_RC1_FAULT reason=%s",reason);
    host_ready_=false;host_touch_active_=host_output_active_=false;
    host_output_end_=host_output_started_=false;
    host_feedback_.clear();host_stop_id_.clear();host_playback_id_.clear();
    host_next_retry_ms_=gobot::NowMs()+4000;
    audio_service_.EnableVoiceProcessing(false);
    audio_service_.ResetDecoder();
    if(protocol_) protocol_->CloseAudioChannel();
    notice_="HOST: связь потеряна";notice_until_=gobot::NowMs()+3000;
    RenderGoBot();
}

void Application::HostEnable(bool enabled) {
    // Selection never writes NVS or modifies the enrolled endpoint.
    if(gobot_turn_.Active() || GetDeviceState()!=kDeviceStateIdle ||
       !audio_service_.IsPlaybackIdle()) {
        ESP_LOGW(TAG,"GOBOT_HOST_SWITCH_REJECT busy=1");return;
    }
    auto* ws=static_cast<WebsocketProtocol*>(protocol_.get());
    if(!ws)return;
    if(!enabled) {
        host_mode_=host_ready_=host_touch_active_=host_output_active_=false;
        host_output_end_=host_output_started_=host_muted_=false;
        host_feedback_.clear();host_stop_id_.clear();host_playback_id_.clear();
        audio_service_.EnableVoiceProcessing(false);audio_service_.ResetDecoder();
        ws->CloseAudioChannel();ws->ConfigureHostTest("");
        ESP_LOGI(TAG,"GOBOT_HOST_MODE OFF volatile=1");RenderGoBot();return;
    }
    if(gobot_muted_ || !gobot_network_ready_ ||
       std::string(GOBOT_HOST_RC1_TEST_URL).empty()) {
        ESP_LOGW(TAG,"GOBOT_HOST_SWITCH_REJECT no_network_or_test_url=1");return;
    }
    if(!ws->ConfigureHostTest(GOBOT_HOST_RC1_TEST_URL)) {
        ESP_LOGE(TAG,"GOBOT_HOST_SWITCH_REJECT protocol_busy=1");return;
    }
    host_mode_=true;host_muted_=false;host_ready_=false;
    host_touch_active_=host_output_active_=false;
    host_output_end_=host_output_started_=false;
    host_next_retry_ms_=gobot::NowMs();
    audio_service_.SetLocalScan(false);
    ESP_LOGI(TAG,"GOBOT_HOST_MODE ON volatile=1 paid=0");
    RenderGoBot();
}

void Application::HostDriverOutputStarted() {
    if(!host_mode_ || !host_ready_)return;
    if(!host_feedback_.empty() && !host_cue_acked_) {
        const auto id=host_feedback_;
        HostControl("gobot_host_ack",",\"feedback_id\":\""+id+
                    "\",\"event\":\"cue_started\"");
        host_cue_acked_=true;
        if(host_render_acked_)host_feedback_.clear();
    } else if(host_output_active_ && !host_output_started_) {
        auto* ws=static_cast<WebsocketProtocol*>(protocol_.get());
        if(ws && ws->HostPlaybackStarted(host_playback_id_,host_output_epoch_)) {
            host_output_started_=true;
            HostControl("gobot_host_playback",",\"playback_id\":\""+host_playback_id_+
                        "\",\"output_epoch\":"+std::to_string(host_output_epoch_)+
                        ",\"playing\":true");
        }
    }
}

void Application::HostOnControl(const cJSON* root) {
    const auto type=gobot::String(root,"type",80);
    if(!type || !host_mode_)return;
    auto* ws=static_cast<WebsocketProtocol*>(protocol_.get());
    if(!ws)return;
    const auto session=gobot::String(root,"session_id",80);
    const auto epoch=gobot::String(root,"epoch",80);
    if(!session || !epoch)return;
    const std::string kind(type);
    if(kind=="gobot_host_ready") {
        auto frame=cJSON_GetObjectItem(root,"frame_samples");
        if(!cJSON_IsNumber(frame) || frame->valueint!=960 ||
           !ws->HostReady(session,epoch)) {HostFault("ready_invalid");return;}
        host_ready_=true;host_touch_active_=false;
        audio_service_.SetLocalScan(false);
        audio_service_.EnableDeviceAec(true);
        audio_service_.EnableVoiceProcessing(true);
        if(!audio_service_.IsAudioProcessorRunning()) {
            HostFault("mic_processor_offline");return;
        }
        HostControl("gobot_host_ready_ack",",\"frame_samples\":960");
        ESP_LOGI(TAG,"GOBOT_HOST_READY epoch_new=1 mic=1 paid=0");
        RenderGoBot();return;
    }
    if(!host_ready_ || !ws->HostScope(session,epoch))return;
    if(kind=="gobot_host_event") {
        const auto event=gobot::String(root,"event",20);
        const auto feedback=gobot::String(root,"feedback_id",80);
        if(!event || !feedback)return;
        if(!strcmp(event,"wake")) {
            if(!host_feedback_.empty())return;
            host_touch_active_=true;host_voice_seen_=false;
            host_feedback_=feedback;host_cue_acked_=host_render_acked_=false;
            RenderGoBot();
            // LVGL refresh completion is the receipt boundary; source rendering
            // alone is NOT proof the LCD driver processed this new frame.
            if(!gobot_host::OnNextNativeRefresh([this,id=host_feedback_]() {
                Schedule([this,id]() {
                    if(host_mode_ && host_ready_ && host_feedback_==id &&
                       !host_render_acked_) {
                        HostControl("gobot_host_ack",",\"feedback_id\":\""+id+
                                    "\",\"event\":\"rendered\"");
                        host_render_acked_=true;
                        if(host_cue_acked_)host_feedback_.clear();
                    }
                });
            })) {HostFault("lcd_refresh_receipt_unavailable");return;}
            audio_service_.PlaySound(Lang::Sounds::OGG_POPUP);
        } else if(!strcmp(event,"stop")) {
            auto generation=cJSON_GetObjectItem(root,"output_epoch");
            if(!cJSON_IsNumber(generation) || generation->valueint<0 ||
               !ws->HostStop(session,epoch,generation->valueint)) {
                HostFault("stop_epoch_invalid");return;
            }
            host_output_epoch_=generation->valueint;
            host_stop_id_=feedback;
            host_output_active_=host_output_started_=host_output_end_=false;
            host_touch_active_=false;host_feedback_.clear();host_playback_id_.clear();
            audio_service_.ResetDecoder();
            RenderGoBot();
        }
    } else if(kind=="gobot_host_output_start") {
        const auto id=gobot::String(root,"playback_id",80);
        const auto gen=cJSON_GetObjectItem(root,"output_epoch");
        if(!id || !cJSON_IsNumber(gen) || gen->valueint!=int(host_output_epoch_)) {
            HostFault("output_start_invalid");return;
        }
        host_playback_id_=id;host_output_active_=true;
        host_output_started_=host_output_end_=false;
        host_touch_active_=false;
        RenderGoBot();
    } else if(kind=="gobot_host_output_end") {
        const auto id=gobot::String(root,"playback_id",80);
        const auto gen=cJSON_GetObjectItem(root,"output_epoch");
        if(!id || host_playback_id_!=id || !cJSON_IsNumber(gen) ||
           gen->valueint!=int(host_output_epoch_)) {
            HostFault("output_end_invalid");return;
        }
        host_output_end_=true;
    } else if(kind=="gobot_host_idle") {
        host_touch_active_=false;host_voice_seen_=false;
        RenderGoBot();
    }
}

void Application::HostTick() {
    if(!host_mode_)return;
    const uint64_t now=gobot::NowMs();
    if(host_muted_ || !gobot_network_ready_) {
        if(host_ready_)HostFault("muted_or_wifi_down");
        return;
    }
    auto* ws=static_cast<WebsocketProtocol*>(protocol_.get());
    if(!ws)return;
    if(ws->HostProtocolFault()) {HostFault("invalid_transport_frame");return;}
    if(!host_ready_) {
        if(now<host_next_retry_ms_)return;
        host_next_retry_ms_=now+5000;
        // One existing protocol; never call the paid Brain gateway.
        if(!protocol_->IsAudioChannelOpened() && !protocol_->OpenAudioChannel()) {
            ESP_LOGW(TAG,"GOBOT_HOST_TEST_CONNECT_FAILED retry_ms=5000");
            protocol_->CloseAudioChannel();
        }
        RenderGoBot();return;
    }
    // Stop receipt only after actual audio queue/software-driver drain.
    if(!host_stop_id_.empty() && audio_service_.IsPlaybackIdle()) {
        HostControl("gobot_host_ack",",\"feedback_id\":\""+host_stop_id_+
                    "\",\"event\":\"stopped\",\"output_epoch\":"+
                    std::to_string(host_output_epoch_));
        host_stop_id_.clear();
    }
    // Never report drained on output_end alone.
    if(host_output_end_ && host_output_started_ && audio_service_.IsPlaybackIdle()) {
        if(ws->HostPlaybackDrained(host_playback_id_,host_output_epoch_)) {
            HostControl("gobot_host_playback",",\"playback_id\":\""+
                        host_playback_id_+"\",\"output_epoch\":"+
                        std::to_string(host_output_epoch_)+",\"playing\":false");
            host_output_active_=host_output_started_=host_output_end_=false;
            host_playback_id_.clear();RenderGoBot();
        } else HostFault("playback_drain_invalid");
    }
    if(host_touch_active_) {
        bool speaking=audio_service_.IsVoiceDetected();
        if(speaking) {
            host_voice_seen_=true;host_last_speech_ms_=now;
        } else if(host_voice_seen_ && now>=host_last_speech_ms_+800) {
            HostControl("gobot_host_finish");
            host_touch_active_=false;
            RenderGoBot();
        } else if(now>host_touch_started_ms_+14000) {
            HostControl("gobot_host_finish");
            host_touch_active_=false;
            RenderGoBot();
        }
    }
}
