#pragma once
// HOST-B ESP_LOCAL Sophia engineering handoff, no I2S/codec/flash/budget calls.
// The *existing HOST-A microphone producer* sends 16 kHz mono PCM16
// packets to the worker; do not create a second I2S/ES8311 reader.
#include <cstddef>
#include <cstdint>

namespace gobot_sophia {
enum class WakeOwner : uint8_t { PLAN_STREAM=0, ESP_LOCAL_SOPHIA=1 };
enum class DevicePhase : uint8_t {
    IDLE=0, LISTENING=1, SPEAKING=2, MUTED=3, STOPPING=4
};

struct WakeEvidence {
    uint64_t sample_end;
    uint64_t packet_received_us;
    uint64_t detected_us;
    uint64_t inference_duration_us;
    uint32_t epoch;
    uint32_t generation;
};

class ExclusiveWakeGate {
public:
    WakeOwner owner() const { return owner_; }
    DevicePhase phase() const { return phase_; }
    uint32_t generation() const { return generation_; }
    void set_phase(DevicePhase next) {
        phase_=next;
        if(next==DevicePhase::IDLE) latched_=false;
    }
    void set_pending(bool p) { pending_=p; }
    bool switch_to(WakeOwner next) {
        if(phase_!=DevicePhase::IDLE || pending_ || latched_) return false;
        if(owner_!=next) { owner_=next; ++generation_; }
        return true;
    }
    bool eligible_for_local_wake() const {
        return owner_==WakeOwner::ESP_LOCAL_SOPHIA &&
               phase_==DevicePhase::IDLE && !pending_ && !latched_;
    }
    bool accept_local_wake(uint32_t gen, uint64_t sample_end) {
        if(!eligible_for_local_wake() || gen!=generation_ ||
           sample_end<=last_accepted_end_) return false;
        latched_=true;
        last_accepted_end_=sample_end;
        return true;
    }
    bool allow_plan_wake() const {
        return owner_==WakeOwner::PLAN_STREAM && phase_==DevicePhase::IDLE &&
               !pending_ && !latched_;
    }
    void begin_new_audio_epoch() {
        ++generation_;
        last_accepted_end_=0;
        latched_=false;
    }
private:
    WakeOwner owner_{WakeOwner::PLAN_STREAM};
    DevicePhase phase_{DevicePhase::IDLE};
    uint32_t generation_{0};
    uint64_t last_accepted_end_{0};
    bool pending_{false};
    bool latched_{false};
};

// Meant to live in the separate WakeNet worker, NOT inside the I2S ISR.
// A should copy each existing Opus producer frame once into a bounded queue.
class ContiguousMonoPcmTap {
public:
    static constexpr size_t kNativeChunkMax=4096;
    explicit ContiguousMonoPcmTap(size_t native_chunk):chunk_(native_chunk){}
    bool valid() const { return chunk_>0 && chunk_<=kNativeChunkMax; }
    void reset() { fill_=0; next_=0; has_sequence_=false; }
    template<typename Notify>
    bool feed(uint32_t epoch, uint64_t sample_start, const int16_t *pcm,
              size_t samples, Notify &&on_full_chunk) {
        if(!valid() || !pcm || samples==0 || samples>960) return false;
        if(!has_sequence_) {
            epoch_=epoch; next_=sample_start; has_sequence_=true;
        }
        if(epoch_!=epoch || sample_start!=next_) {
            ++dropped_gaps_; reset();
            return false;  // never feed stale or discontinuous microphone data
        }
        for(size_t i=0; i<samples; i++) {
            chunk_buffer_[fill_++]=pcm[i];
            ++next_;
            if(fill_==chunk_) {
                on_full_chunk(chunk_buffer_, chunk_, next_);
                fill_=0;
            }
        }
        return true;
    }
    uint64_t dropped_gaps() const { return dropped_gaps_; }
    size_t pending_samples() const { return fill_; }
private:
    int16_t chunk_buffer_[kNativeChunkMax]{};
    size_t chunk_;
    size_t fill_{0};
    uint32_t epoch_{0};
    uint64_t next_{0};
    uint64_t dropped_gaps_{0};
    bool has_sequence_{false};
};
} // namespace gobot_sophia