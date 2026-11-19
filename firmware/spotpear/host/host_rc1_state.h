#pragma once
// HOST-A RC1: bounded deterministic hardware transport state, no SDK dependencies.
// A failed sequence, generation, or output epoch must close the TEST stream;
// never silently conceal missing microphone samples or replay old output.
#include <cstdint>
#include <mutex>
#include <string>
#include "host_client_state.h"

namespace gobot_host {
class Rc1Stream {
    mutable std::mutex mu_;
    std::string session_, epoch_, playback_;
    bool ready_=false, output_active_=false, pending_binary_=false;
    bool output_complete_=false, started_=false, drained_=false;
    uint64_t first_producer_seq_=0, expected_producer_seq_=0;
    bool first_producer_seen_=false;
    uint32_t output_epoch_=0, expected_packet_=0, total_packets_=0;
public:
    void Clear() {
        std::lock_guard<std::mutex> lock(mu_);
        ready_=false;session_.clear();epoch_.clear();playback_.clear();
        output_active_=pending_binary_=output_complete_=started_=drained_=false;
        expected_packet_=total_packets_=output_epoch_=0;
        first_producer_seen_=false;first_producer_seq_=expected_producer_seq_=0;
    }
    bool Ready(const std::string& session,const std::string& epoch) {
        std::lock_guard<std::mutex> lock(mu_);
        if(ready_ || !identifier(session) || !identifier(epoch))return false;
        session_=session;epoch_=epoch;ready_=true;return true;
    }
    bool IsReady() const {
        std::lock_guard<std::mutex> lock(mu_);return ready_;
    }
    bool Scope(const std::string& session,const std::string& epoch) const {
        std::lock_guard<std::mutex> lock(mu_);
        return ready_ && session==session_ && epoch==epoch_;
    }
    std::string Session() const {std::lock_guard<std::mutex> lock(mu_);return session_;}
    std::string Epoch() const {std::lock_guard<std::mutex> lock(mu_);return epoch_;}
    // Producer counter is assigned by the actual Opus encoder, BEFORE its send
    // queue can drop frames. Counter normalization is per authenticated epoch.
    bool SendPosition(uint64_t producer,uint32_t& sequence) {
        std::lock_guard<std::mutex> lock(mu_);
        if(!ready_)return false;
        if(!first_producer_seen_) {
            first_producer_seen_=true;first_producer_seq_=producer;
            expected_producer_seq_=producer;
        }
        if(producer!=expected_producer_seq_ ||
           producer-first_producer_seq_>UINT32_MAX/960)return false;
        sequence=static_cast<uint32_t>(producer-first_producer_seq_);
        ++expected_producer_seq_;return true;
    }
    bool OutputStart(const std::string& session,const std::string& epoch,
                     const std::string& playback,uint32_t generation,uint32_t count) {
        std::lock_guard<std::mutex> lock(mu_);
        if(!ready_||session!=session_||epoch!=epoch_||!identifier(playback)||
           output_active_||pending_binary_||generation!=output_epoch_||
           count==0||count>64)return false;
        playback_=playback;output_active_=true;pending_binary_=false;
        output_complete_=started_=drained_=false;
        expected_packet_=0;total_packets_=count;return true;
    }
    bool OutputMetadata(const std::string& session,const std::string& epoch,
                        const std::string& playback,uint32_t generation,uint32_t sequence,
                        uint32_t start,uint32_t count) {
        std::lock_guard<std::mutex> lock(mu_);
        if(!ready_||session!=session_||epoch!=epoch_||!output_active_||
           pending_binary_||output_complete_||playback!=playback_||
           generation!=output_epoch_||sequence!=expected_packet_||
           sequence>=total_packets_||count!=1440||start!=sequence*1440)return false;
        pending_binary_=true;return true;
    }
    bool ConsumeBinary() {
        std::lock_guard<std::mutex> lock(mu_);
        if(!ready_||!output_active_||!pending_binary_)return false;
        pending_binary_=false;++expected_packet_;return true;
    }
    bool OutputEnd(const std::string& session,const std::string& epoch,
                   const std::string& playback,uint32_t generation,uint32_t count) {
        std::lock_guard<std::mutex> lock(mu_);
        if(!ready_||session!=session_||epoch!=epoch_||!output_active_||
           pending_binary_||output_complete_||playback!=playback_||
           generation!=output_epoch_||count!=total_packets_||
           count!=expected_packet_)return false;
        output_complete_=true;return true;
    }
    bool PlaybackStarted(const std::string& id,uint32_t generation) {
        std::lock_guard<std::mutex> lock(mu_);
        if(!output_active_||playback_!=id||generation!=output_epoch_||
           started_||drained_)return false;
        started_=true;return true;
    }
    bool PlaybackDrained(const std::string& id,uint32_t generation) {
        std::lock_guard<std::mutex> lock(mu_);
        if(!output_active_||playback_!=id||generation!=output_epoch_||
           !started_||!output_complete_||drained_)return false;
        drained_=true;output_active_=false;playback_.clear();return true;
    }
    bool Stop(const std::string& session,const std::string& epoch,uint32_t next_generation) {
        std::lock_guard<std::mutex> lock(mu_);
        if(!ready_||session!=session_||epoch!=epoch_||
           next_generation!=output_epoch_+1)return false;
        output_epoch_=next_generation;playback_.clear();output_active_=false;
        pending_binary_=output_complete_=started_=drained_=false;
        expected_packet_=total_packets_=0;return true;
    }
    uint32_t OutputEpoch() const {
        std::lock_guard<std::mutex> lock(mu_);return output_epoch_;
    }
};
} // namespace gobot_host
