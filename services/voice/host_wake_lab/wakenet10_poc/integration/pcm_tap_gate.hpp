// GoBot HOST-B isolated integration proposal: no I2S, codec, WiFi or NVS calls.
// HOST-A must explicitly review and adapt this header into its RC1 audio path.
// WakeNet never opens a microphone: it reads a COPY of the SAME PCM producer.
#pragma once
#include <cstddef>
#include <cstdint>

namespace gobot_wn10 {
enum class Source : uint8_t { PLAN_STREAM = 0, ESP_LOCAL_WAKENET10 = 1 };
enum class Phase : uint8_t { IDLE = 0, LISTENING = 1, SPEAKING = 2, MUTED = 3, STOP_PENDING = 4 };

class SourceGate {
public:
    Source active() const { return source_; }
    Phase phase() const { return phase_; }
    uint32_t generation() const { return generation_; }
    bool select(Source next) {
        if (phase_ != Phase::IDLE || pending_) return false;
        if (source_ != next) {
            source_ = next;
            latched_ = false;
            ++generation_;
        }
        return true;
    }
    void phase(Phase next) {
        phase_ = next;
        if (next == Phase::IDLE) latched_ = false;
    }
    void set_pending(bool next) { pending_ = next; }
    // Local wake MUST have a genuine approved Russian Monika model manifest.
    // Official demo wn10_ru_privetesp may be compiled, but cannot wake GoBot.
    bool on_local_detection(bool approved_monika_weights, uint32_t generation,
                            uint64_t sample_end) {
        if (!approved_monika_weights || source_ != Source::ESP_LOCAL_WAKENET10 ||
            phase_ != Phase::IDLE || pending_ || latched_ ||
            generation != generation_ || sample_end <= last_sample_end_) return false;
        latched_ = true;
        last_sample_end_ = sample_end;
        return true;
    }
    bool allow_plan_detection() const {
        return source_ == Source::PLAN_STREAM &&
               phase_ == Phase::IDLE && !pending_ && !latched_;
    }
    void reset_stream_epoch() {
        latched_ = false;
        last_sample_end_ = 0;
        ++generation_;
    }
private:
    Source source_{Source::PLAN_STREAM};
    Phase phase_{Phase::IDLE};
    bool pending_{false};
    bool latched_{false};
    uint32_t generation_{0};
    uint64_t last_sample_end_{0};
};

class PcmTap {
public:
    static constexpr size_t kMaxSamples = 2048;
    explicit PcmTap(size_t model_chunk) : chunk_(model_chunk) {}
    bool valid() const { return chunk_ >= 1 && chunk_ <= kMaxSamples; }
    void reset() { fill_ = 0; next_sample_ = 0; initialized_ = false; }
    // The source_seq*960 PCM comes from HOST-A's existing producer, NOT an
    // additional I2S reader. Callback receives complete native model chunks.
    // If a gap occurs, refuse the sample and reset before processing again.
    template <typename Callback>
    bool feed(const int16_t *pcm, size_t samples,
              uint64_t start_sample, Callback &&on_chunk) {
        if (!valid() || !pcm || !samples || samples > 960) return false;
        if (!initialized_) { next_sample_ = start_sample; initialized_ = true; }
        if (start_sample != next_sample_) {
            reset(); return false;
        }
        for (size_t i = 0; i < samples; ++i) {
            frame_[fill_++] = pcm[i];
            ++next_sample_;
            if (fill_ == chunk_) {
                on_chunk(frame_, chunk_, next_sample_);
                fill_ = 0;
            }
        }
        return true;
    }
    size_t buffered() const { return fill_; }
private:
    int16_t frame_[kMaxSamples]{};
    size_t chunk_{0};
    size_t fill_{0};
    uint64_t next_sample_{0};
    bool initialized_{false};
};
} // namespace gobot_wn10
