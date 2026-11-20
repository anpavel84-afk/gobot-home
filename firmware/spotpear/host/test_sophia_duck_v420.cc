// Compile production gesture/mute dispatch and exact production control branches.
// Audio, JSON and transport edges are deterministic stubs; no hardware is used.
#include <atomic>
#include <cassert>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <map>
#include <memory>
#include <mutex>
#include <functional>
#include <string>
#include <vector>
#include "host_touch_gesture.h"
#include "host_barge_wake.h"

#define ESP_LOGI(...) do {} while (false)
constexpr int kAbortReasonNone=0;
uint64_t test_now=1000;
uint64_t esp_timer_get_time(){return test_now*1000;}
std::vector<std::string> ordered;
int hardware_volume=50;
bool codec_failure=false;
constexpr int ESP_CODEC_DEV_OK=0;
#define ESP_ERROR_CHECK(value) assert((value)==ESP_CODEC_DEV_OK)
int esp_codec_dev_set_out_vol(void*,int volume) {
    ordered.push_back("hardware:"+std::to_string(volume));
    if(codec_failure)return -1;
    hardware_volume=volume;return ESP_CODEC_DEV_OK;
}
class AudioCodec {
public:
    int output_volume_=50,persistent_writes=0;
    virtual void SetOutputVolume(int volume){output_volume_=volume;++persistent_writes;}
};
class Es8311AudioCodec:public AudioCodec {
public:
    std::mutex data_if_mutex_;
    int output_attenuation_percent_=100;
    void* dev_=this;
#include "native_effective_volume.inc"
    void SetOutputVolume(int volume) override;
    bool SetTransientOutputAttenuation(int percent);
};
#include "native_codec_volume.inc"
#include "native_codec_attenuation.inc"
struct Board {
    static Board& GetInstance(){static Board value;return value;}
    Es8311AudioCodec codec;
    Es8311AudioCodec* GetAudioCodec(){return &codec;}
};

struct cJSON {
    enum Kind {Object,Boolean,Number,Text} kind=Object;
    bool boolean=false;
    double valuedouble=0;
    int valueint=0;
    std::string text;
    std::map<std::string,cJSON> fields;
    static cJSON Bool(bool value){cJSON out;out.kind=Boolean;out.boolean=value;return out;}
    static cJSON Num(double value){cJSON out;out.kind=Number;out.valuedouble=value;out.valueint=value>=0 && value<=INT32_MAX?int(value):0;return out;}
    static cJSON Str(const char* value){cJSON out;out.kind=Text;out.text=value;return out;}
};
const cJSON* cJSON_GetObjectItem(const cJSON* value,const char* key) {
    if(!value)return nullptr;
    const auto found=value->fields.find(key);
    return found==value->fields.end()?nullptr:&found->second;
}
bool cJSON_IsNumber(const cJSON* value){return value && value->kind==cJSON::Number;}
bool cJSON_IsBool(const cJSON* value){return value && value->kind==cJSON::Boolean;}
bool cJSON_IsTrue(const cJSON* value){return cJSON_IsBool(value) && value->boolean;}
char* cJSON_PrintUnformatted(const cJSON*){return nullptr;}
void cJSON_free(void*){}

namespace gobot {
uint64_t NowMs(){return test_now;}
enum class Phase {Idle,Capturing,Speaking};
struct Turn {Phase phase=Phase::Idle;bool Active()const{return phase!=Phase::Idle;} Phase GetPhase()const{return phase;}};
const char* String(const cJSON* value,const char* key,size_t limit) {
    const auto field=cJSON_GetObjectItem(value,key);
    return field && field->kind==cJSON::Text && field->text.size()<=limit?field->text.c_str():nullptr;
}
}
namespace gobot_host {
bool OnNextNativeRefresh(std::function<void()> callback){callback();return true;}
bool wire_identifier(const char* value){return value && *value;}
}
namespace gobot_raw_wake {bool touch(bool,bool,uint64_t){return false;}}

struct Audio {
    bool wake=true,capture=true,scan=true,processing=true,idle=true,drained=true;
    bool diagnostic=true,device_aec=false;
    uint32_t epoch=1;
    unsigned decoder_resets=0;
    void AllowHostWake(bool enabled){wake=enabled;}
    void AllowHostInterrupt(bool){wake=true;}
    void EnableHostCapture(bool enabled){capture=enabled;wake=enabled;++epoch;if(enabled)scan=true;}
    void SetLocalScan(bool enabled){scan=enabled;}
    void EnableVoiceProcessing(bool enabled){processing=enabled;}
    void EnableSophiaDiagnostic(bool enabled){diagnostic=enabled;}
    void EnableDeviceAec(bool enabled){device_aec=enabled;}
    bool IsAudioProcessorRunning()const{return processing;}
    void ResetDecoder(){++decoder_resets;ordered.push_back("decoder_reset");}
    uint32_t HostCaptureEpoch()const{return epoch;}
    uint64_t HostCaptureSampleEnd()const{return 0;}
    bool LocalWakePending()const{return false;}
    bool IsPlaybackIdle()const{return idle;}
    bool HardwareOutputDrained()const{return drained;}
};
struct WebsocketProtocol {
    bool v2=true,opened=true;
    unsigned closes=0,aborts=0;
    bool HostV2()const{return v2;}
    bool IsAudioChannelOpened()const{return opened;}
    void CloseAudioChannel(){opened=false;++closes;}
    void SendAbortSpeaking(int){++aborts;}
    std::string HostStreamEpoch(uint32_t epoch)const{return "epoch-"+std::to_string(epoch);}
    bool HostReady(const char*,const char*,int){return true;}
};
struct Admission {bool blocked=false;bool KnownBlocked()const{return blocked;}void Reset(){}};
struct Receipts {void Reset(){}};

class Application {
public:
    void TouchGesture(bool physical,bool hold);
    void HostSetMuted(bool muted,bool notify=true);
    bool HostBeginInterrupt(const std::string& id,bool listen,bool duck=false);
    void HostReleaseOutputDuck();
    void HostSophiaWake(uint32_t capture_epoch,uint64_t sample,uint64_t detected_us,uint64_t callback_us);
    std::string HostBargeStats()const;
    void Schedule(std::function<void()> callback){callback();}
    std::string HostInterruptFields()const{return ",\"interrupt_requested\":true";}
    void RenderGoBot(){++renders;}
    void GoBotFinish(const char*){gobot_turn_.phase=gobot::Phase::Idle;}
    void StartGoBotTurn(const char*){gobot_turn_.phase=gobot::Phase::Capturing;}
    void HostConnectDone(bool){++connect_done;}
    void HostFault(const char* reason){fault=reason;audio_service_.EnableHostCapture(false);}
    void HostControl(const std::string& type,const std::string& fields) {
        if(!host_ready_ || !protocol_->IsAudioChannelOpened())return;
        if(type=="gobot_host_mute" && fields.find("\"muted\":true")!=std::string::npos)
            assert(!audio_service_.wake && !audio_service_.capture && !audio_service_.scan && !audio_service_.processing);
        sent.push_back(type+fields);
    }
    void Ready(const cJSON* root) {
        auto* ws=protocol_.get();
        const char *session="session",*epoch="epoch";
#include "native_ready_body.inc"
    }
    void Complete(const cJSON* root) {
#include "native_interrupt_body.inc"
    }
    void RemoteMute(const cJSON* root) {
#include "native_mute_body.inc"
    }
    void StartOutput(const cJSON* root) {
        auto* ws=protocol_.get();
#include "native_output_start.inc"
    }
    void ResumeListen() {
        auto* ws=protocol_.get();const uint64_t now=gobot::NowMs();
#include "native_resume_block.inc"
    }
    bool host_mode_=true,host_ready_=true,host_muted_=false,gobot_muted_=false;
    bool host_touch_active_=false,host_response_busy_=false,host_voice_seen_=false;
    bool host_unified_=true,host_probe_wake_pending_=false;
    std::atomic<bool> host_output_active_{false},host_connecting_{false};
    bool host_touch_resume_pending_=false,host_interrupt_quiet_sent_=false;
    bool host_whole_response_=false,host_output_end_=false,host_output_started_=false;
    bool timer_latched_=false;
    bool host_output_ducked_=false;
    uint64_t host_duck_started_=0,host_duck_restored_=0;
    uint32_t host_barge_wakes_=0;
    std::string host_output_kind_;
    uint32_t host_mute_revision_=0,host_output_epoch_=0,host_wake_sequence_=0;
    unsigned touch_events_=0,host_barge_taps_=0,renders=0,connect_done=0;
    uint64_t last_contact_=0,host_touch_started_ms_=0,host_ready_deadline_ms_=0,host_next_retry_ms_=0;
    std::string gobot_ui_phase_,host_feedback_,host_playback_id_,host_response_id_,host_stop_id_;
    std::string host_connect_abort_reason_,host_deferred_ready_,timer_key_,fault;
    gobot::Turn gobot_turn_;
    Audio audio_service_;
    Admission host_admission_ui_;
    Receipts host_output_receipts_;
    gobot_host::InterruptLatch host_interrupt_;
    std::unique_ptr<WebsocketProtocol> protocol_=std::make_unique<WebsocketProtocol>();
    std::vector<std::string> sent;
};

#include "host_touch_controls.inc"
#include "native_begin_interrupt.inc"
#include "native_duck_release.inc"
#include "native_sophia_wake.inc"
#include "native_barge_stats.inc"

cJSON ready() {
    cJSON value;
    value.fields={{"protocol",cJSON::Num(2)},{"frame_samples",cJSON::Num(960)},
        {"pcm_stage",cJSON::Str("pre_afe")},{"wake_location",cJSON::Str("ESP")}};
    return value;
}
cJSON completion(const std::string& id,const char* outcome) {
    cJSON value;value.fields={{"event_id",cJSON::Str(id.c_str())},{"outcome",cJSON::Str(outcome)}};return value;
}
cJSON mute(bool muted,double revision) {
    cJSON value;value.fields={{"muted",cJSON::Bool(muted)},{"mute_revision",cJSON::Num(revision)}};return value;
}
bool contains(const Application& app,const std::string& value) {
    for(const auto& event:app.sent)if(event.find(value)!=std::string::npos)return true;
    return false;
}
void gestures() {
    using G=gobot_host::TouchGesture;
    gobot_host::TouchPress press;
    assert(press.Update(true,1000)==G::None);
    assert(press.Update(true,1649)==G::None);
    assert(press.Update(true,1650)==G::Hold);
    assert(press.Update(true,90000)==G::None);
    assert(press.Update(false,90001)==G::None);
    assert(press.Update(false,91000)==G::None);
    assert(press.Update(true,92000)==G::None);
    assert(press.Update(false,92039)==G::None);
    assert(press.Update(true,93000)==G::None);
    assert(press.Update(false,93040)==G::Tap);
    assert(press.Update(true,94000)==G::None);
    assert(press.Update(false,94649)==G::Tap);
    assert(press.Update(true,95000)==G::None);
    assert(press.Update(false,95650)==G::Hold);
    assert(press.Update(true,96000)==G::None);
    assert(press.Update(true,95999)==G::None);
    assert(press.Update(false,97000)==G::None);
}
void all_states_mute() {
    for(unsigned state=0;state<9;++state) {
        Application app;test_now=1000;app.last_contact_=999;
        if(state==1)app.host_touch_active_=true;
        if(state==2)app.host_response_busy_=true;
        if(state==3)app.host_output_active_=true;
        if(state==4)assert(app.host_interrupt_.Begin("pending",900,true));
        if(state==5)app.host_ready_=false;
        if(state==6){app.host_ready_=false;app.host_connecting_=true;}
        if(state==7){app.host_mode_=false;app.gobot_turn_.phase=gobot::Phase::Capturing;}
        if(state==8)app.host_touch_resume_pending_=true;
        app.TouchGesture(true,true);
        assert(app.host_muted_ && app.gobot_muted_ && !app.host_touch_resume_pending_);
        assert(!app.audio_service_.capture && !app.audio_service_.scan && !app.audio_service_.wake && !app.audio_service_.processing);
        assert(!app.host_interrupt_.Listen());
        assert(app.host_mute_revision_==1);
        app.TouchGesture(true,true);
        assert(app.host_muted_ && app.host_mute_revision_==2);
        assert(!contains(app,"\"muted\":false"));
    }
}
void short_toggle_and_stale_completions() {
    Application app;test_now=1000;
    app.TouchGesture(true,false);assert(app.host_touch_active_);
    assert(contains(app,"\"action\":\"activate\""));
    test_now=1400;app.TouchGesture(true,false);
    assert(!app.host_touch_active_ && app.host_interrupt_.Pending() && !app.host_interrupt_.Listen());
    auto done=completion(app.host_interrupt_.Id(),"ready");app.Complete(&done);
    assert(!app.host_touch_active_ && !app.host_muted_ && !app.host_interrupt_.Pending());

    Application busy;test_now=2000;busy.host_response_busy_=true;
    busy.TouchGesture(true,false);assert(busy.host_interrupt_.Pending() && busy.host_interrupt_.Listen());
    const std::string id=busy.host_interrupt_.Id();
    test_now=2400;busy.TouchGesture(true,false);
    assert(!busy.host_interrupt_.Listen() && !busy.host_touch_active_);
    done=completion(id,"listening");busy.Complete(&done);
    assert(!busy.host_touch_active_ && !busy.host_interrupt_.Pending());

    Application held;test_now=3000;held.host_response_busy_=true;
    held.TouchGesture(true,false);done=completion(held.host_interrupt_.Id(),"listening");
    test_now=3100;held.TouchGesture(true,true);held.Complete(&done);
    assert(held.host_muted_ && !held.host_touch_active_ && !held.audio_service_.capture);
}
void remote_revision_and_handshake() {
    Application app;test_now=4000;
    auto old=mute(false,0);app.TouchGesture(true,true);app.RemoteMute(&old);
    assert(app.host_muted_ && !app.audio_service_.scan && app.protocol_->closes==0);
    old.fields.erase("mute_revision");app.RemoteMute(&old);assert(app.host_muted_);
    old=mute(false,1);app.TouchGesture(true,true);app.RemoteMute(&old);
    assert(app.host_muted_ && app.host_mute_revision_==2);
    auto hello=ready();app.host_ready_=false;app.Ready(&hello);
    assert(app.host_ready_ && app.host_muted_ && !app.audio_service_.capture && !app.audio_service_.scan);
    assert(contains(app,"\"mute_revision\":2,\"muted\":true"));
    auto current=mute(false,2);app.RemoteMute(&current);
    assert(!app.host_muted_ && app.audio_service_.scan && !app.audio_service_.capture);
    assert(app.protocol_->closes==1 && app.host_mute_revision_==2);

    Application overflow;overflow.host_mute_revision_=UINT32_MAX-1;test_now=5000;
    overflow.TouchGesture(true,true);assert(overflow.host_mute_revision_==UINT32_MAX);
    test_now=5500;overflow.TouchGesture(true,false);
    assert(overflow.host_muted_ && !overflow.host_touch_resume_pending_);
    current=mute(false,double(UINT32_MAX));overflow.RemoteMute(&current);
    assert(overflow.host_muted_ && overflow.host_mute_revision_==UINT32_MAX);

    Application restore;test_now=6000;restore.TouchGesture(true,true);
    test_now=6500;restore.TouchGesture(true,false);
    assert(!restore.host_muted_ && restore.host_touch_resume_pending_ && !restore.host_ready_);
    assert(restore.host_mute_revision_==2 && !restore.audio_service_.capture);
    restore.protocol_->opened=true;restore.Ready(&hello);restore.ResumeListen();
    assert(restore.host_touch_active_ && !restore.host_touch_resume_pending_ && restore.audio_service_.capture);
    assert(contains(restore,"gobot_host_mute,\"muted\":false,\"mute_revision\":2"));
    const auto count=restore.sent.size();restore.ResumeListen();assert(count==restore.sent.size());
}
void duck_and_restore_actual_handlers() {
    auto& codec=Board::GetInstance().codec;
    auto reset_codec=[&](){codec.output_volume_=50;codec.persistent_writes=0;
        codec.output_attenuation_percent_=100;hardware_volume=50;codec_failure=false;ordered.clear();};
    reset_codec();
    Application app;app.host_output_active_=true;app.host_response_busy_=true;
    app.audio_service_.idle=false;app.audio_service_.drained=false;
    app.HostSophiaWake(app.audio_service_.epoch,500,1000,1100);
    assert(app.host_interrupt_.Pending() && app.host_interrupt_.Listen());
    assert(app.host_output_ducked_ && app.host_duck_started_==1 && app.host_barge_wakes_==1);
    assert(ordered.size()==2 && ordered[0]=="hardware:10" && ordered[1]=="decoder_reset");
    assert(hardware_volume==10 && codec.output_volume_==50 && codec.persistent_writes==0);
    assert(contains(app,"gobot_host_wake") && contains(app,"\"interrupt_requested\":true"));
    assert(app.HostBargeStats().find("\"barge_duck_active\":true")!=std::string::npos);
    app.HostSophiaWake(app.audio_service_.epoch,600,1200,1300);
    assert(app.host_duck_started_==1 && app.host_barge_wakes_==1);
    app.HostReleaseOutputDuck();assert(hardware_volume==10);
    app.audio_service_.idle=true;app.HostReleaseOutputDuck();assert(hardware_volume==10);
    app.audio_service_.idle=false;app.audio_service_.drained=true;
    app.HostReleaseOutputDuck();assert(hardware_volume==10);
    codec.SetOutputVolume(80);assert(hardware_volume==16 && codec.output_volume_==80 && codec.persistent_writes==1);
    test_now+=1000;app.TouchGesture(true,true);assert(app.host_muted_ && !app.audio_service_.capture);
    app.audio_service_.idle=true;app.audio_service_.drained=true;app.HostReleaseOutputDuck();
    assert(hardware_volume==80 && codec.output_volume_==80 && codec.persistent_writes==1);
    assert(!app.host_output_ducked_ && app.host_duck_restored_==1 && app.host_muted_);
    assert(!app.audio_service_.capture && !app.audio_service_.processing);

    reset_codec();Application offline;offline.host_output_active_=true;
    offline.audio_service_.idle=false;offline.audio_service_.drained=false;
    assert(offline.HostBeginInterrupt("wake-2",true,true));
    offline.host_mode_=false;offline.host_ready_=false;
    offline.HostReleaseOutputDuck();assert(hardware_volume==10);
    offline.audio_service_.idle=true;offline.audio_service_.drained=true;
    offline.HostReleaseOutputDuck();assert(hardware_volume==50 && !offline.host_output_ducked_);

    reset_codec();Application tap;tap.host_output_active_=true;
    assert(tap.HostBeginInterrupt("touch-3",true));
    assert(hardware_volume==50 && !tap.host_output_ducked_ && ordered.size()==1 && ordered[0]=="decoder_reset");
    Application thinking;thinking.host_response_busy_=true;
    thinking.HostSophiaWake(thinking.audio_service_.epoch,100,1000,1001);
    assert(thinking.host_barge_wakes_==1 && !thinking.host_output_ducked_ && hardware_volume==50);

    reset_codec();codec_failure=true;Application failure;failure.host_output_active_=true;
    assert(failure.HostBeginInterrupt("wake-4",true,true));
    assert(!failure.host_output_ducked_ && failure.audio_service_.decoder_resets==1 && hardware_volume==50);
    codec_failure=false;
    assert(!codec.SetTransientOutputAttenuation(-1) && !codec.SetTransientOutputAttenuation(101));
    assert(codec.persistent_writes==0);

    reset_codec();Application next;next.host_output_active_=true;
    next.audio_service_.idle=false;next.audio_service_.drained=false;
    next.HostSophiaWake(next.audio_service_.epoch,300,1000,1001);
    next.host_output_active_=false;next.audio_service_.idle=true;next.audio_service_.drained=true;
    auto done=completion(next.host_interrupt_.Id(),"listening");next.Complete(&done);
    assert(hardware_volume==50 && !next.host_output_ducked_ && next.host_touch_active_);
    cJSON start;start.fields={{"playback_id",cJSON::Str("new-output")},{"response_id",cJSON::Str("new-response")},
        {"output_epoch",cJSON::Num(next.host_output_epoch_)},{"kind",cJSON::Str("answer")}};
    next.StartOutput(&start);assert(next.host_output_active_ && hardware_volume==50 && !next.host_output_ducked_);
    reset_codec();Application muted;muted.host_muted_=true;muted.host_output_active_=true;
    muted.HostSophiaWake(muted.audio_service_.epoch,100,1000,1001);assert(ordered.empty());
    Application stale;stale.host_output_active_=true;
    stale.HostSophiaWake(stale.audio_service_.epoch+1,100,1000,1001);assert(ordered.empty());
}

int main() {
    duck_and_restore_actual_handlers();
    gestures();all_states_mute();short_toggle_and_stale_completions();remote_revision_and_handshake();
    std::cout<<"PASS actual wake duck/hardware attenuation/no NVS/current-volume restore/DMA barrier/touch/mute controls\n";
}
