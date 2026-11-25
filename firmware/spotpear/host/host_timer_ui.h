#pragma once
#include <cstdint>
#include <cstring>
#include <cmath>
#include <limits>
#include "host_admission_ui.h"

// Fixed-size display state only. No capture, wake, grant, volume or playback
// authority is granted by a timer update. The host owns durable wall time;
// this presentation uses a local monotonic deadline between host snapshots.
namespace gobot_host {
enum class TimerUpdate : uint8_t { Invalid=0, Accepted=1, Duplicate=2, Stale=3 };

class TimerUi {
public:
    void ResetTransport() {revision_=0;reported_=false;}

    TimerUpdate Update(double revision,const char* state,const char* id,
                       double remaining_ms,uint64_t now) {
        if(!std::isfinite(revision) || revision<1 || revision>0xffffffffULL ||
           revision!=std::floor(revision) || !std::isfinite(remaining_ms) ||
           remaining_ms<0 || remaining_ms>86400000 || remaining_ms!=std::floor(remaining_ms) ||
           !state || !id)return TimerUpdate::Invalid;
        const bool clear=!std::strcmp(state,"clear");
        const bool running=!std::strcmp(state,"running");
        const bool expired=!std::strcmp(state,"expired");
        if((!clear && !running && !expired) || (clear?*id!=0:!Uuid(id)) ||
           (!running && remaining_ms!=0) || (running && remaining_ms<1) ||
           now>std::numeric_limits<uint64_t>::max()-static_cast<uint64_t>(remaining_ms))return TimerUpdate::Invalid;
        const auto next=static_cast<uint32_t>(revision);
        if(next<revision_)return TimerUpdate::Stale;
        if(next==revision_)return !std::strcmp(id,id_) && !std::strcmp(state,state_) &&
            remaining_ms==remaining_ms_?TimerUpdate::Duplicate:TimerUpdate::Invalid;
        revision_=next;remaining_ms_=static_cast<uint32_t>(remaining_ms);
        std::strcpy(id_,id);std::strcpy(state_,state);
        deadline_=running?now+remaining_ms_:0;
        reported_=false;
        return TimerUpdate::Accepted;
    }

    bool ObserveRender(NativeRenderResult result,bool timer_visible) {
        if(!revision_ || result==NativeRenderResult::Failed)return false;
        const bool rendered=timer_visible && std::strcmp(state_,"clear");
        if(reported_ && rendered_==rendered)return false;
        reported_=true;rendered_=rendered;result_=result;return true;
    }
    uint32_t Revision() const {return revision_;}
    const char* Id() const {return id_;}
    const char* State() const {return state_;}
    uint64_t Deadline() const {return deadline_;}
    bool Expired() const {return !std::strcmp(state_,"expired");}
    bool Rendered() const {return rendered_;}
    const char* Evidence() const {
        return result_==NativeRenderResult::Invalidated?
            "native_framebuffer_invalidated":"native_framebuffer_unchanged";
    }

private:
    uint32_t revision_=0,remaining_ms_=0;
    uint64_t deadline_=0;
    char id_[37]={},state_[8]="clear";
    bool reported_=false,rendered_=false;
    NativeRenderResult result_=NativeRenderResult::Failed;
    static bool Uuid(const char* value) {
        if(std::strlen(value)!=36)return false;
        for(unsigned i=0;i<36;++i) {
            const char c=value[i];
            if(i==8 || i==13 || i==18 || i==23) {if(c!='-')return false;}
            else if(!((c>='0' && c<='9') || (c>='a' && c<='f')))return false;
        }
        return true;
    }
};
static_assert(sizeof(TimerUi)<=80,"Timer presentation must stay bounded");
}
