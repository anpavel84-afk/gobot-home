#pragma once
// Content-free first-reply probe. Output write != physical acoustic onset.
// Does not capture audio, change AEC, open connections or grant paid sessions.
#include <array>
#include <cstdint>
#include <cstdio>
#include <mutex>
#include <string>
#include "host_client_state.h"
namespace gobot_latency {
enum class Event:unsigned { Activation, Capture, FirstSpeech, LastSpeech, End,
    Packet, WriteEnter, WriteReturn, TasksDrained, Count };
inline const char* name(Event e) {
    static constexpr const char* names[]={"activation_accepted","capture_begin",
        "mic_first_speech","mic_last_speech","utterance_end_decided",
        "output_packet_received","output_write_enter","output_write_return","output_tasks_drained"};
    return names[static_cast<unsigned>(e)];
}
struct Stamp {Event event;uint64_t us=0;bool pending=false,seen=false;};
class Probe {
    std::mutex mutex_;
    std::array<Stamp,static_cast<unsigned>(Event::Count)> values_{};
    bool active_=false,reply_started_=false,last_vad_=false;
    uint64_t last_speech_=0;unsigned seq_=0;
    std::string trace_,session_,clock_,kind_="unknown";
    void note(Event e,uint64_t now,bool replace=false) {
        auto& s=values_[static_cast<unsigned>(e)];
        if(s.seen&&!replace)return;
        s={e,now,true,true};
    }
public:
    void Begin(uint64_t now) {
        std::lock_guard<std::mutex> lock(mutex_);
        values_={};active_=true;reply_started_=last_vad_=false;last_speech_=0;seq_=0;
        trace_.clear();session_.clear();clock_.clear();kind_="unknown";note(Event::Activation,now);
    }
    bool Bind(const std::string& trace,const std::string& session,const std::string& clock,const std::string& kind) {
        std::lock_guard<std::mutex> lock(mutex_);
        if(!active_||!trace_.empty()||!gobot_host::identifier(trace)||!gobot_host::identifier(session)||!gobot_host::identifier(clock))return false;
        if(kind!="unknown"&&kind!="provider_reply"&&kind!="fixture")return false;
        trace_=trace;session_=session;clock_=clock;kind_=kind;return true;
    }
    void Mic(bool vad,uint64_t now) {
        std::lock_guard<std::mutex> lock(mutex_);
        if(!active_||reply_started_)return;
        note(Event::Capture,now);
        if(vad){note(Event::FirstSpeech,now);last_speech_=now;}
        else if(last_vad_&&last_speech_)note(Event::LastSpeech,last_speech_,true);
        last_vad_=vad;
    }
    void End(uint64_t now) {
        std::lock_guard<std::mutex> lock(mutex_);if(!active_)return;
        if(last_speech_)note(Event::LastSpeech,last_speech_,true);note(Event::End,now);
    }
    void Packet(uint64_t now) {std::lock_guard<std::mutex> lock(mutex_);if(active_)note(Event::Packet,now);}
    void WriteEnter(uint64_t now) {
        std::lock_guard<std::mutex> lock(mutex_);if(!active_)return;
        reply_started_=true;if(last_speech_)note(Event::LastSpeech,last_speech_,true);note(Event::WriteEnter,now);
    }
    void WriteReturn(uint64_t now) {std::lock_guard<std::mutex> lock(mutex_);if(active_&&reply_started_)note(Event::WriteReturn,now);}
    void TasksDrained(uint64_t now) {std::lock_guard<std::mutex> lock(mutex_);if(active_&&reply_started_)note(Event::TasksDrained,now);}
    std::string Next(const std::string& session) {
        std::lock_guard<std::mutex> lock(mutex_);
        if(trace_.empty()||session!=session_)return {};
        for(auto& s:values_)if(s.pending){
            s.pending=false;char out[650];
            const bool audio=static_cast<unsigned>(s.event)>=static_cast<unsigned>(Event::Packet);
            snprintf(out,sizeof(out),"{\"type\":\"gobot_latency\",\"session_id\":\"%s\",\"trace_id\":\"%s\",\"clock_epoch\":\"%s\",\"turn\":0,\"seq\":%u,\"device_us\":%llu,\"event\":\"%s\",\"audio_kind\":\"%s\"}",
                session_.c_str(),trace_.c_str(),clock_.c_str(),seq_++,static_cast<unsigned long long>(s.us),name(s.event),audio?kind_.c_str():"unknown");
            return out;
        }
        return {};
    }
};
inline Probe& probe(){static Probe value;return value;}
}
