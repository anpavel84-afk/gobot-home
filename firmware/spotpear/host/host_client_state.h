#pragma once
// Issue #4: pure state for the opt-in HOST client. No model, network or NVS.
#include <cstdint>
#include <limits>
#include <string>
#include <utility>

namespace gobot_host {
constexpr uint32_t kFrameSamples = 960;
constexpr uint64_t kMaxSourceAgeMs = 250;
constexpr unsigned kQueueFrames = 4;
inline bool identifier(const std::string& value) {
    if(value.empty() || value.size()>64)return false;
    for(unsigned char c:value)if(!((c>='a'&&c<='z')||(c>='A'&&c<='Z')||(c>='0'&&c<='9')||c=='-'))return false;
    return true;
}
struct SourceFrame { uint32_t generation=0, sequence=0; uint64_t captured_ms=0; };
class ClientState {
public:
    bool selected=false, ready=false, capture=false;
    uint32_t generation=0, expected_sequence=0, output_epoch=0;
    std::string session, epoch, feedback, stop_id;
    bool rendered=false, cue_started=false, stopping=false;
    uint64_t ready_deadline=0, activation_deadline=0;
    uint32_t cue_id=0;
    void invalidate() {
        ++generation; ready=capture=false; expected_sequence=0; output_epoch=0;
        session.clear();epoch.clear();feedback.clear();stop_id.clear();
        rendered=cue_started=stopping=false;ready_deadline=activation_deadline=0;cue_id=0;
    }
    bool select(bool on,bool idle) {
        if(!idle)return false;
        invalidate();selected=on;return true;
    }
    bool begin_ready(const std::string& s,const std::string& e,unsigned samples,uint64_t now) {
        if(!selected || ready || !identifier(s)||!identifier(e)||samples!=kFrameSamples)return false;
        session=s;epoch=e;ready=true;capture=false;expected_sequence=0;ready_deadline=now+2000;return true;
    }
    bool capture_after_ack(bool sent) {
        if(!ready || !sent)return false;
        capture=true;ready_deadline=0;return true;
    }
    bool same(const std::string& s,const std::string& e)const {return ready&&s==session&&e==epoch;}
    bool accept_source(const SourceFrame& f,uint64_t now) {
        if(!capture||f.generation!=generation||f.sequence!=expected_sequence||
           now<f.captured_ms||now-f.captured_ms>kMaxSourceAgeMs||
           expected_sequence==std::numeric_limits<uint32_t>::max())return false;
        ++expected_sequence;return true;
    }
    bool wake(const std::string& id,uint64_t now) {
        if(!ready || !identifier(id)||!feedback.empty()||stopping)return false;
        feedback=id;rendered=cue_started=false;activation_deadline=now+10000;
        ++cue_id;if(!cue_id)++cue_id;return true;
    }
    bool acknowledge_render(uint32_t gen,const std::string& id) {
        if(!ready||gen!=generation||id!=feedback||id.empty()||rendered)return false;
        rendered=true;return true;
    }
    bool acknowledge_cue(uint32_t gen,uint32_t id) {
        if(!ready||gen!=generation||id!=cue_id||feedback.empty()||cue_started||stopping)return false;
        cue_started=true;return true;
    }
    bool request_stop(const std::string& id,uint32_t new_epoch) {
        if(!ready||!identifier(id)||stopping||new_epoch!=output_epoch+1)return false;
        output_epoch=new_epoch;stop_id=id;stopping=true;activation_deadline=0;return true;
    }
    bool complete_stop(bool output_idle) {
        if(!stopping||!output_idle)return false;
        stopping=false;feedback.clear();rendered=cue_started=false;return true;
    }
    void idle() {feedback.clear();activation_deadline=0;rendered=cue_started=false;}
};
}
