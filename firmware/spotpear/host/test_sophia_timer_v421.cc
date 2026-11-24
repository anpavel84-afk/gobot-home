// Actual candidate control and render receipt methods; websocket/JSON/LCD edges
// are inert native stubs. No microphone, model, transport or physical board.
#include <cassert>
#include <iostream>
#include <map>
#include <memory>
#include <string>
#include <vector>
#include "host_timer_ui.h"

struct cJSON {
    enum Kind {Object,Number,String,Bool} kind=Object;
    double valuedouble=0;
    std::string text;
    const char* valuestring=nullptr;
    std::map<std::string,cJSON> fields;
    static cJSON NumberValue(double value) {cJSON j;j.kind=Number;j.valuedouble=value;return j;}
    void Put(const std::string& key,const std::string& value) {
        auto& node=fields[key];node.kind=String;node.text=value;node.valuestring=node.text.c_str();
    }
};
const cJSON* cJSON_GetObjectItem(const cJSON* root,const char* key) {
    if(!root)return nullptr;
    auto it=root->fields.find(key);return it==root->fields.end()?nullptr:&it->second;
}
bool cJSON_IsNumber(const cJSON* j) {return j && j->kind==cJSON::Number;}
bool cJSON_IsString(const cJSON* j) {return j && j->kind==cJSON::String;}
namespace gobot {
uint64_t clock_ms=1000;
uint64_t NowMs() {return clock_ms;}
const char* String(const cJSON* root,const char* key,size_t limit) {
    const auto j=cJSON_GetObjectItem(root,key);
    return cJSON_IsString(j) && j->text.size()<=limit?j->valuestring:nullptr;
}
}
struct WebsocketProtocol {
    bool v2=true,scope=true;
    bool HostV2() const {return v2;}
    bool HostScope(const char* session,const char* epoch) const {
        return scope && std::string(session)=="current" && std::string(epoch)=="epoch";
    }
};
class Application {
public:
    bool host_mode_=true,host_ready_=true,host_muted_=true,host_touch_active_=true;
    bool host_response_busy_=true,host_output_active_=true,timer_latched_=false;
    unsigned capture_calls=0,wake_calls=0,sound_calls=0,render_calls=0;
    uint64_t gobot_timer_end_=0;
    std::string timer_key_;
    gobot_host::TimerUi host_timer_ui_;
    std::unique_ptr<WebsocketProtocol> protocol_=std::make_unique<WebsocketProtocol>();
    std::vector<std::string> receipts;
    void HostControl(const std::string& type,const std::string& extra) {receipts.push_back(type+extra);}
    void RenderGoBot() {++render_calls;}
    void HostTimerControl(const cJSON* root);
    void HostTimerRendered(bool visible,gobot_host::NativeRenderResult result);
};
#include "native_timer_control.inc"
#include "native_timer_rendered.inc"

static void Make(cJSON& data,double revision,const std::string& state,
                 const std::string& id,double remaining) {
    data.Put("session_id","current");data.Put("epoch","epoch");
    data.Put("state",state);data.Put("timer_id",id);
    data.fields["revision"]=cJSON::NumberValue(revision);
    data.fields["remaining_ms"]=cJSON::NumberValue(remaining);
}

int main() {
    using gobot_host::TimerUpdate;
    using gobot_host::NativeRenderResult;
    const char* id="12345678-1234-1234-1234-123456789abc";
    gobot_host::TimerUi timer;
    assert(timer.Update(1,"running",id,10000,1000)==TimerUpdate::Accepted);
    assert(timer.Deadline()==11000);
    assert(timer.Update(1,"running",id,10000,4000)==TimerUpdate::Duplicate);
    assert(timer.Deadline()==11000); // Same packet cannot reset countdown.
    assert(timer.Update(1,"running",id,7000,4000)==TimerUpdate::Invalid);
    assert(timer.Update(0,"expired",id,0,4000)==TimerUpdate::Invalid);
    assert(timer.Update(3,"expired",id,0,11000)==TimerUpdate::Accepted && timer.Expired());
    assert(timer.Update(2,"running",id,1000,11000)==TimerUpdate::Stale);
    assert(!timer.ObserveRender(NativeRenderResult::Failed,true));
    assert(timer.ObserveRender(NativeRenderResult::Invalidated,true) && timer.Rendered());
    assert(!timer.ObserveRender(NativeRenderResult::Unchanged,true));
    assert(timer.Update(4,"clear","",0,11000)==TimerUpdate::Accepted);
    assert(timer.Deadline()==0 && !timer.Expired());
    assert(timer.ObserveRender(NativeRenderResult::Unchanged,true) && !timer.Rendered());
    for(double invalid : {-1.,0.5,4294967296.,double(NAN),double(INFINITY)})
        assert(timer.Update(invalid,"running",id,1000,0)==TimerUpdate::Invalid);
    for(double invalid : {-1.,0.,0.5,86400001.,double(NAN),double(INFINITY)})
        assert(timer.Update(5,"running",id,invalid,0)==TimerUpdate::Invalid);
    assert(timer.Update(5,"running","not-an-id",1000,0)==TimerUpdate::Invalid);
    assert(timer.Update(5,"speak",id,1000,0)==TimerUpdate::Invalid);
    assert(timer.Update(5,"expired",id,1000,0)==TimerUpdate::Invalid);
    assert(timer.Update(5,"clear",id,0,0)==TimerUpdate::Invalid);
    assert(timer.Update(5,"running",id,1,std::numeric_limits<uint64_t>::max())==TimerUpdate::Invalid);
    assert(timer.Update(5,"running",id,10000,1000)==TimerUpdate::Accepted);
    timer.ResetTransport();
    assert(timer.Deadline()==11000 && timer.Revision()==0);
    assert(!timer.ObserveRender(NativeRenderResult::Invalidated,true));
    assert(timer.Update(1,"running",id,7000,4000)==TimerUpdate::Accepted);
    assert(timer.Deadline()==11000); // Reconnected host restores remaining time.

    Application app;
    cJSON data;Make(data,1,"running",id,10000);
    for(unsigned boundary=0;boundary<6;++boundary) {
        app.host_mode_=boundary!=0;app.host_ready_=boundary!=1;
        app.protocol_->v2=boundary!=2;app.protocol_->scope=boundary!=3;
        data.Put("session_id",boundary==4?"old":"current");
        data.Put("epoch",boundary==5?"old":"epoch");
        app.HostTimerControl(&data);
        assert(!app.render_calls && !app.gobot_timer_end_);
    }
    app.host_mode_=app.host_ready_=app.protocol_->v2=app.protocol_->scope=true;
    Make(data,1,"running",id,10000);
    app.HostTimerControl(&data);
    assert(app.gobot_timer_end_==11000 && app.render_calls==1);
    assert(app.host_muted_ && app.host_touch_active_ && app.host_response_busy_ && app.host_output_active_);
    assert(!app.capture_calls && !app.wake_calls && !app.sound_calls);
    gobot::clock_ms=4000;app.HostTimerControl(&data);
    assert(app.render_calls==1 && app.gobot_timer_end_==11000);
    app.HostTimerRendered(true,NativeRenderResult::Failed);
    assert(app.receipts.empty());
    app.HostTimerRendered(true,NativeRenderResult::Invalidated);
    assert(app.receipts.size()==1 && app.receipts.back().find("native_framebuffer_invalidated")!=std::string::npos);
    assert(app.receipts.back().find("\"rendered\":true")!=std::string::npos);
    app.HostTimerRendered(true,NativeRenderResult::Unchanged);assert(app.receipts.size()==1);
    Make(data,2,"expired",id,0);app.HostTimerControl(&data);
    assert(!app.gobot_timer_end_ && app.timer_latched_);
    Make(data,3,"clear","",0);app.HostTimerControl(&data);
    assert(!app.gobot_timer_end_ && !app.timer_latched_ && app.timer_key_.empty());
    app.HostTimerRendered(false,NativeRenderResult::Unchanged);
    assert(app.receipts.back().find("\"rendered\":false")!=std::string::npos);
    Make(data,4,"running",id,1000);data.fields["revision"].kind=cJSON::Bool;
    const auto renders=app.render_calls;app.HostTimerControl(&data);
    assert(app.render_calls==renders);
    std::cout<<"PASS actual timer scope/types/monotonic deadline/replay/clear/reconnect/mute isolation/native framebuffer receipts\n";
}
