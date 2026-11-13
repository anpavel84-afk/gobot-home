#pragma once
#include <cstdint>

// Main-task-owned policy. No transport, audio, clock or operating-system calls.
// Session state is finite, and only an explicit wake creates a new turn.
namespace gobot {
enum class Phase { Idle, Connecting, Capturing, Waiting, Speaking, Draining };
enum class Action { None, StopCapture, Finish, Timeout };
class TurnGuard {
public:
    bool Begin(uint64_t now) {
        if (phase_ != Phase::Idle || now < cooldown_until_) return false;
        phase_ = Phase::Connecting; since_ = now; last_voice_ = now;
        heard_voice_ = false; ++generation_; return true;
    }
    bool Connected(uint64_t now) {
        if (phase_ != Phase::Connecting) return false;
        phase_ = Phase::Capturing; since_ = last_voice_ = now;
        heard_voice_ = false; return true;
    }
    bool TtsStart(uint64_t now) {
        if (phase_ == Phase::Speaking) return true;
        if (phase_ != Phase::Waiting) return false;
        phase_ = Phase::Speaking; since_ = now; return true;
    }
    bool TtsStop(uint64_t now) {
        if (phase_ != Phase::Speaking) return false;
        phase_ = Phase::Draining; since_ = now; return true;
    }
    void End(uint64_t now) {
        phase_ = Phase::Idle; heard_voice_ = false;
        cooldown_until_ = now + 1000;
    }
    Action Poll(uint64_t now, bool voice, bool playback_idle) {
        const uint64_t age = now >= since_ ? now - since_ : 0;
        switch (phase_) {
        case Phase::Idle: return Action::None;
        case Phase::Connecting: return age >= 15000 ? Action::Timeout : Action::None;
        case Phase::Capturing:
            if (voice) { heard_voice_ = true; last_voice_ = now; }
            if (!heard_voice_ && age >= 6000) return Action::Finish;
            if ((heard_voice_ && !voice && now >= last_voice_ + 800) || age >= 25000) {
                phase_ = Phase::Waiting; since_ = now; return Action::StopCapture;
            }
            return Action::None;
        case Phase::Waiting: return age >= 65000 ? Action::Timeout : Action::None;
        case Phase::Speaking: return age >= 180000 ? Action::Timeout : Action::None;
        case Phase::Draining:
            if (playback_idle) return Action::Finish;
            return age >= 8000 ? Action::Timeout : Action::None;
        }
        return Action::Timeout;
    }
    bool UploadAllowed() const { return phase_ == Phase::Capturing; }
    bool Active() const { return phase_ != Phase::Idle; }
    Phase GetPhase() const { return phase_; }
    uint64_t Generation() const { return generation_; }
private:
    Phase phase_ = Phase::Idle;
    uint64_t since_ = 0, last_voice_ = 0, cooldown_until_ = 0, generation_ = 0;
    bool heard_voice_ = false;
};
}
