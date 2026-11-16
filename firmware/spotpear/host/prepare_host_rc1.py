"""Patch a separate validated 0.4.12 XiaoZhi source COPY into HOST-A RC1.

Never patches working 0.4.12, NVS, bootloader, OTA partitions or the live
gateway. The test endpoint is passed via a private build-only header.
No physical install happens here. Run only against private RC1 staging copy.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

VERSION = "0.4.13-dev-host-a-rc1-r3"
BASE = "0.4.12-dev-guided-calibration-1"


def prepare(root: Path, test_url: str):
    root = root.resolve()
    if not test_url.startswith("wss://") or not test_url.endswith("/xiaozhi/v1/"):
        raise ValueError("isolated_wss_test_endpoint_required")
    if not 1 <= len(test_url) <= 230 or '"' in test_url or '\\' in test_url:
        raise ValueError("invalid_wss_test_endpoint")
    if (root / "CMakeLists.txt").read_text().count(BASE) != 1:
        raise ValueError("must_patch_unmodified_0412_copy")
    if not (root / "main" / "host_rc1_state.h").is_file() or not (root / "main" / "host_rc1_render_ack.h").is_file():
        raise ValueError("missing_reviewed_host_state_or_render_ack_header")

    modified = []

    def replace(path: str, before: str, after: str):
        f = root / path
        original = f.read_text(encoding="utf8")
        if original.count(before) != 1:
            raise ValueError(f"missing_or_ambiguous_patch_anchor:{path}:{before[:70]!r}:count={original.count(before)}")
        f.write_text(original.replace(before, after), encoding="utf8")
        modified.append(path)

    replace("CMakeLists.txt", BASE, VERSION)
    replace("main/gobot_build_info.h", BASE, VERSION)

    # Build-only endpoint: no NVS migration and no public enrollment secret.
    private = root / "main" / "gobot_host_rc1_private.h"
    if private.exists():
        raise FileExistsError("private_test_url_header_already_exists")
    private.write_text('#pragma once\n#define GOBOT_HOST_RC1_TEST_URL "' + test_url + '"\n')
    private.chmod(0o600)

    replace("main/protocols/protocol.h",
            "    uint32_t playback_id = 0;",
            "    uint32_t playback_id = 0;\n    uint64_t host_producer_seq = 0;")

    replace("main/audio/audio_service.h",
            "    std::function<void(void)> on_playback_drained;",
            "    std::function<void(void)> on_playback_drained;\n    std::function<void(void)> on_driver_output_started;")
    replace("main/audio/audio_service.h",
            "    std::atomic<bool> service_stopped_{true};",
            "    std::atomic<uint64_t> host_encoder_seq_{0};\n    std::atomic<bool> service_stopped_{true};")
    replace("main/audio/audio_service.cc",
            "            packet->timestamp = task.timestamp;",
            "            packet->timestamp = task.timestamp;\n            packet->host_producer_seq = host_encoder_seq_.fetch_add(1);")
    replace("main/audio/audio_service.cc",
            "        codec_->OutputData(task.pcm);",
            "        codec_->OutputData(task.pcm);\n        // Driver has accepted the buffer; actual acoustic onset is unverified.\n        if(callbacks_.on_driver_output_started)callbacks_.on_driver_output_started();")

    wshead = "main/protocols/websocket_protocol.h"
    replace(wshead, '#include "protocol.h"',
            '#include "protocol.h"\n#include "host_rc1_state.h"')
    replace(wshead, "    bool IsAudioChannelOpened() const override;",
            """    bool IsAudioChannelOpened() const override;
    bool ConfigureHostTest(const std::string& url);
    bool HostReady(const std::string& session,const std::string& epoch);
    bool HostScope(const std::string& session,const std::string& epoch) const;
    bool HostStop(const std::string& session,const std::string& epoch,uint32_t generation);
    bool HostPlaybackStarted(const std::string& id,uint32_t generation);
    bool HostPlaybackDrained(const std::string& id,uint32_t generation);
    bool HostSend(const std::string& body);
    bool HostProtocolFault() const {return host_rx_invalid_.load();}
    std::string HostEpoch() const;
    std::string HostSession() const;
    bool HostTest() const { return host_test_; }""")
    replace(wshead, "    int version_ = 1;",
            """    int version_ = 1;
    bool host_test_ = false;
    std::string host_test_url_;
    gobot_host::Rc1Stream host_state_;
    std::mutex host_send_mutex_;
    std::atomic<bool> host_rx_invalid_{false};""")

    wsc = "main/protocols/websocket_protocol.cc"
    replace(wsc, "#include <cstring>",
            "#include <cstring>\n#include <limits>\n#include <mutex>")
    replace(wsc, 'bool WebsocketProtocol::SendAudio(std::unique_ptr<AudioStreamPacket> packet) {',
            """bool WebsocketProtocol::ConfigureHostTest(const std::string& url) {
    if(websocket_ && websocket_->IsConnected())return false;
    if(!url.empty() && (url.rfind("wss://",0)!=0 ||
       url.size()>240 || url.find("/xiaozhi/v1/")==std::string::npos))return false;
    host_test_=!url.empty();host_test_url_=url;
    host_state_.Clear();host_rx_invalid_=false;return true;
}
bool WebsocketProtocol::HostReady(const std::string& session,const std::string& epoch) {
    return host_test_ && session==session_id_ && host_state_.Ready(session,epoch);
}
bool WebsocketProtocol::HostScope(const std::string& session,const std::string& epoch) const {
    return host_test_ && host_state_.Scope(session,epoch);
}
bool WebsocketProtocol::HostStop(const std::string& session,const std::string& epoch,uint32_t gen) {
    return host_test_ && host_state_.Stop(session,epoch,gen);
}
bool WebsocketProtocol::HostPlaybackStarted(const std::string& id,uint32_t gen) {
    return host_test_ && host_state_.PlaybackStarted(id,gen);
}
bool WebsocketProtocol::HostPlaybackDrained(const std::string& id,uint32_t gen) {
    return host_test_ && host_state_.PlaybackDrained(id,gen);
}
bool WebsocketProtocol::HostSend(const std::string& body) {
    if(!host_test_ || !host_state_.IsReady() || host_rx_invalid_)return false;
    // Serialize JSON control with metadata+Opus binary atomic pair.
    std::lock_guard<std::mutex> guard(host_send_mutex_);
    return SendText(body);
}
std::string WebsocketProtocol::HostEpoch() const {return host_state_.Epoch();}
std::string WebsocketProtocol::HostSession() const {return host_state_.Session();}

bool WebsocketProtocol::SendAudio(std::unique_ptr<AudioStreamPacket> packet) {
    if(host_test_) {
        uint32_t seq=0;
        if(!packet || packet->frame_duration!=60 || packet->sample_rate!=16000 ||
           !host_state_.SendPosition(packet->host_producer_seq,seq)) {
            host_rx_invalid_=true;ESP_LOGE(TAG,"HOST_CAPTURE_GAP_OR_WRONG_FORMAT");
            return false;
        }
        // Must serialize metadata and payload on the SAME websocket.
        std::lock_guard<std::mutex> guard(host_send_mutex_);
        char meta[340];
        snprintf(meta,sizeof(meta),"{\\"type\\":\\"gobot_host_frame\\",\\"session_id\\":\\"%s\\",\\"epoch\\":\\"%s\\",\\"seq\\":%lu,\\"sample_start\\":%lu,\\"sample_count\\":960}",
                 host_state_.Session().c_str(),host_state_.Epoch().c_str(),
                 (unsigned long)seq,(unsigned long)(seq*960));
        if(host_rx_invalid_ || !websocket_ || !websocket_->IsConnected() || !websocket_->Send(meta) ||
           !websocket_->Send(packet->payload.data(),packet->payload.size(),true)) {
            host_rx_invalid_=true;return false;
        }
        return true;
    }""")

    replace(wsc,
            "    ++generation_;\n    websocket_.reset();",
            "    ++generation_;\n    host_state_.Clear();host_rx_invalid_=false;\n    websocket_.reset();")
    replace(wsc,
            "    const std::string url=enrollment.url;",
            "    const std::string url=host_test_?host_test_url_:enrollment.url;\n    host_state_.Clear();host_rx_invalid_=false;")
    replace(wsc,
            "        if(generation!=generation_.load() || (binary?len>4096:len>16384))return;",
            """        if(generation!=generation_.load())return;
        if(binary?len>4096:len>16384) {
            if(host_test_)host_rx_invalid_=true;
            return;
        }
        if(host_test_ && host_rx_invalid_.load())return;""")
    replace(wsc,
            "        if (binary) {\n            if (on_incoming_audio_ != nullptr) {",
            """        if (binary) {
            if(host_test_ && !host_state_.ConsumeBinary()) {
                host_rx_invalid_=true;
                ESP_LOGE(TAG,"HOST_RX_BINARY_WITHOUT_SCOPED_POSITION");return;
            }
            if (on_incoming_audio_ != nullptr) {""")
    replace(wsc, "            // Parse JSON data\n            auto root = cJSON_ParseWithLength(data, len);",
            """            // Parse JSON data
            auto root = cJSON_ParseWithLength(data, len);
            if(!root){host_rx_invalid_=true;return;}
            if(host_test_){
                auto typ=cJSON_GetObjectItem(root,"type");
                auto str=[root](const char* k)->std::string{
                    auto v=cJSON_GetObjectItem(root,k);
                    return cJSON_IsString(v)?std::string(v->valuestring):std::string();
                };
                auto num=[root](const char* k)->uint32_t{
                    auto v=cJSON_GetObjectItem(root,k);
                    return cJSON_IsNumber(v)&&v->valuedouble>=0&&
                           v->valuedouble<=4294967295.0&&
                           v->valuedouble==floor(v->valuedouble)
                        ?static_cast<uint32_t>(v->valuedouble):UINT32_MAX;
                };
                bool valid=true;
                if(cJSON_IsString(typ)) {
                    const std::string kind(typ->valuestring);
                    if(kind=="gobot_host_output_start")
                        valid=host_state_.OutputStart(str("session_id"),str("epoch"),
                            str("playback_id"),num("output_epoch"),num("packet_count")) &&
                            num("sample_rate")==24000 && num("frame_samples")==1440 &&
                            str("audio_kind")=="fixture" && str("codec")=="opus";
                    if(kind=="gobot_host_output_frame")
                        valid=host_state_.OutputMetadata(str("session_id"),str("epoch"),
                            str("playback_id"),num("output_epoch"),num("seq"),
                            num("sample_start"),num("sample_count"));
                    if(kind=="gobot_host_output_end")
                        valid=host_state_.OutputEnd(str("session_id"),str("epoch"),
                            str("playback_id"),num("output_epoch"),num("packet_count"));
                }
                if(!valid){
                    ESP_LOGE(TAG,"HOST_RX_INVALID_FRAME_CONTROL");
                    host_rx_invalid_=true;cJSON_Delete(root);return;
                }
            }""")
    replace(wsc,
            "    cJSON_AddItemToObject(root, \"audio_params\", audio_params);",
            """    cJSON_AddItemToObject(root, "audio_params", audio_params);
    if(host_test_) {
        cJSON* caps=cJSON_CreateObject();
        cJSON_AddNumberToObject(caps,"version",1);
        cJSON_AddStringToObject(caps,"capture","continuous");
        cJSON_AddBoolToObject(caps,"frame_sequence",true);
        cJSON_AddBoolToObject(caps,"local_wake_enabled",false);
        cJSON_AddBoolToObject(caps,"local_feedback",true);
        cJSON_AddBoolToObject(caps,"playback_epoch",true);
        cJSON_AddItemToObject(root,"host_stream",caps);
    }""")
    replace(wsc, '#include <limits>', '#include <limits>\n#include <cmath>')

    # Application: a single main-thread owner of HOST interface, no new task.
    apph = "main/application.h"
    replace(apph, '#include <cstdint>', '#include <cstdint>\n#include <atomic>')
    replace(apph, "    gobot::TurnGuard gobot_turn_;",
            """    gobot::TurnGuard gobot_turn_;
    std::atomic<bool> host_mode_{false},host_ready_{false},host_output_active_{false};
    bool host_muted_=false,host_touch_active_=false,host_voice_seen_=false;
    bool host_output_started_=false,host_output_end_=false;
    bool host_cue_acked_=false, host_render_acked_=false;
    uint32_t host_output_epoch_=0;
    uint64_t host_next_retry_ms_=0,host_touch_started_ms_=0,host_last_speech_ms_=0;
    std::string host_feedback_,host_playback_id_,host_stop_id_;
    void HostEnable(bool on);
    void HostFault(const char* reason);
    void HostTick();
    void HostDriverOutputStarted();
    void HostOnControl(const cJSON* root);
    void HostControl(const std::string& type,const std::string& extras="");""")
    app = "main/application.cc"
    replace(app, '#include "websocket_protocol.h"',
            '#include "websocket_protocol.h"\n#include "gobot_host_rc1_private.h"\n#include "host_rc1_render_ack.h"')
    replace(app, "    callbacks.on_playback_drained = [this]() {",
            """    callbacks.on_driver_output_started = [this]() {
        // Audio-task evidence, forwarded to the existing application main task.
        Schedule([this](){if(host_mode_)HostDriverOutputStarted();});
    };
    callbacks.on_playback_drained = [this]() {""")
    replace(app,
            '                if(local_pause_active_ || !gobot_turn_.UploadAllowed()) continue;',
            """                if(host_mode_) {
                    auto* ws=static_cast<WebsocketProtocol*>(protocol_.get());
                    if(!host_ready_ || host_muted_ || !ws || !ws->SendAudio(std::move(packet))) {
                        if(host_ready_)HostFault("uplink_gap_or_send");
                        while(auto stale=audio_service_.PopPacketFromSendQueue())
                            std::fill(stale->payload.begin(),stale->payload.end(),0);
                        break;
                    }
                    continue;
                }
                if(local_pause_active_ || !gobot_turn_.UploadAllowed()) continue;""")
    replace(app,
            '    protocol_->OnIncomingAudio([this](std::unique_ptr<AudioStreamPacket> packet) {\n        if (GetDeviceState() == kDeviceStateSpeaking) {',
            """    protocol_->OnIncomingAudio([this](std::unique_ptr<AudioStreamPacket> packet) {
        if(host_mode_) {
            // A WSS receive callback can beat the main task's output_start
            // handler. Schedule packets on that same ordered main queue.
            auto frame=std::shared_ptr<AudioStreamPacket>(packet.release());
            Schedule([this,frame](){
                if(!host_ready_ || !host_output_active_)return;
                auto copy=std::make_unique<AudioStreamPacket>(*frame);
                if(!audio_service_.PushPacketToDecodeQueue(std::move(copy)))
                    HostFault("output_queue_overflow");
            });
            return;
        }
        if (GetDeviceState() == kDeviceStateSpeaking) {""")
    replace(app,
            '            if(gobot_turn_.Active()) GoBotFinish("remote_closed");',
            '            if(host_mode_) {host_ready_=false;host_next_retry_ms_=gobot::NowMs()+4000;RenderGoBot();return;}\n            if(gobot_turn_.Active()) GoBotFinish("remote_closed");')
    replace(app,
            '        if(!strcmp(type->valuestring,"gobot_input_end")) {',
            """        if(host_mode_ && !strncmp(type->valuestring,"gobot_host_",11)) {
            char* str=cJSON_PrintUnformatted(root);
            if(str) {
                std::string copy(str);cJSON_free(str);
                Schedule([this,copy=std::move(copy)](){
                    auto msg=cJSON_Parse(copy.c_str());
                    if(msg){HostOnControl(msg);cJSON_Delete(msg);}
                });
            }
            return;
        }
        if(!strcmp(type->valuestring,"gobot_input_end")) {""")
    replace(app,
            '    if(gobot_raw_wake::touch(physical,hold,now)){RenderGoBot();return;}',
            """    if(host_mode_) {
        if(hold) {
            if(host_ready_ && (host_touch_active_ || host_output_active_)) {
                HostControl("gobot_host_touch",",\\"gesture\\":\\"stop\\"");
            } else {
                host_muted_=!host_muted_;
                if(host_muted_){
                    HostControl("gobot_host_mute",",\\"muted\\":true");
                    host_ready_=false;protocol_->CloseAudioChannel();
                    audio_service_.EnableVoiceProcessing(false);
                } else host_next_retry_ms_=now;
            }
        } else if(host_ready_ && !host_muted_ && !host_touch_active_ && !host_output_active_) {
            host_touch_active_=true;host_voice_seen_=false;host_touch_started_ms_=now;
            HostControl("gobot_host_touch",",\\"gesture\\":\\"activate\\"");
        }
        RenderGoBot();return;
    }
    if(gobot_raw_wake::touch(physical,hold,now)){RenderGoBot();return;}""")
    replace(app,
            '    if(page.view==View::Listening) {',
            """    if(host_mode_) {
        page.engine="HOST";
        if(host_muted_)page.view=View::Muted;
        else if(!host_ready_)page.view=View::Connecting;
        else if(host_output_active_)page.view=View::Speaking;
        else if(host_touch_active_)page.view=View::Listening;
        else page.view=View::Ready;
    }
    if(page.view==View::Listening) {""")
    replace(app,
            '    if(gobot_mww::consume_overflow() && gobot_wake_turn_ && gobot_turn_.Active())',
            '    if(host_mode_) {HostTick();RenderGoBot();return;}\n    if(gobot_mww::consume_overflow() && gobot_wake_turn_ && gobot_turn_.Active())')
    replace(app,
            '    if(gobot_raw_wake::command(line,!gobot_turn_.Active() && audio_service_.IsPlaybackIdle(),gobot_muted_,gobot::NowMs()))',
            """    if(line=="GOBOT_HOST_ON"){HostEnable(true);return;}
    if(line=="GOBOT_HOST_OFF"){HostEnable(false);return;}
    if(line=="GOBOT_HOST_TONE"){
        if(host_mode_ && host_ready_ && !host_touch_active_ &&
           !host_output_active_ && host_feedback_.empty())
            HostControl("gobot_host_fixture");
        return;
    }
    if(gobot_raw_wake::command(line,!gobot_turn_.Active() && audio_service_.IsPlaybackIdle(),gobot_muted_,gobot::NowMs()))""")
    replace(app,
            '    if(line.rfind("GOBOT_CFG ",0)==0) {',
            """    if(line.rfind("GOBOT_CFG ",0)==0 && !host_mode_) {""")
    replace("main/touch_screen.h",
            'const char* engine=p.engine=="A"?"Эксперт A":p.engine=="B"?"Разговор B":p.engine=="C"?"Разговор C":"";',
            'const char* engine=p.engine=="HOST"?"HOST":p.engine=="A"?"Эксперт A":p.engine=="B"?"Разговор B":p.engine=="C"?"Разговор C":"";')
    # Append member method implementations at the end, no separate runtime class.
    inc = root / "main/host_rc1_app.inc"
    if not inc.exists():
        raise ValueError("missing_real_device_rc1_methods")
    target = root / app
    with target.open("a", encoding="utf8") as out:
        out.write('\n#include "host_rc1_app.inc"\n')

    manifest = {
        "version": VERSION, "source_version": BASE,
        "sha256_source": {x: hashlib.sha256((root/x).read_bytes()).hexdigest()
                          for x in sorted(set(modified))},
        "host_state_sha256": hashlib.sha256((root/"main/host_rc1_state.h").read_bytes()).hexdigest(),
        "host_app_sha256": hashlib.sha256(inc.read_bytes()).hexdigest(),
        "test_url_compiled_private": True,
        "test_url_not_in_public_manifest": True,
        "local_default_host_disabled": True, "paid_calls": 0,
        "firmware_flashed": False, "full_image_built": False
    }
    (root / "host-rc1-source-manifest.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps({"version": VERSION, "files_modified": len(modified),
                      "status": "SOURCE_PATCHED_NOT_BUILT"}))


if __name__ == "__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("stage", type=Path)
    ap.add_argument("--test-url", required=True)
    opt=ap.parse_args()
    prepare(opt.stage, opt.test_url)
