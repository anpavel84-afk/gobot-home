#pragma once
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <mutex>

// One bounded diagnostic sample, never a second microphone reader. The input
// task supplies the SAME mono PCM block subsequently supplied to microWakeWord.
// All control/export methods have one owner (the application task).
namespace raw_wake {
enum class State { Empty, Armed, Recording, Ready, Failed };
class Capture {
 public:
    Capture(int16_t* storage, size_t capacity): data_(storage), capacity_(capacity) {}
    bool attach(int16_t* storage,size_t capacity) {
        std::lock_guard<std::mutex> lock(mutex_);
        if(state()!=State::Empty || data_ || !storage)return false;
        data_=storage;capacity_=capacity;return true;
    }
    int16_t* release_storage() {
        clear();std::lock_guard<std::mutex> lock(mutex_);
        auto* old=data_;data_=nullptr;capacity_=0;return old;
    }
    bool arm(unsigned seconds, uint64_t now) {
        if (state()!=State::Empty || !data_ || seconds<15 || seconds>60 ||
            size_t(seconds)*16000>capacity_) return false;
        target_=size_t(seconds)*16000; count_=0; expires_=now+120000;
        state_=State::Armed; return true;
    }
    bool start(bool physical, uint64_t now) {
        if (!physical || state()!=State::Armed || now>=expires_) return false;
        deadline_=now+target_/16+2000; expires_=deadline_+20000; state_=State::Recording; return true;
    }
    void feed(const int16_t* pcm, size_t n) {
        if (state()!=State::Recording) return;
        std::unique_lock<std::mutex> lock(mutex_,std::try_to_lock);
        if (!lock.owns_lock()) {state_=State::Failed;return;}
        if (state()!=State::Recording) return;
        const size_t left=target_-count_.load(); if(n>left)n=left;
        std::memcpy(data_+count_.load(),pcm,n*sizeof(int16_t)); count_+=n;
        if(count_.load()==target_){State expected=State::Recording;state_.compare_exchange_strong(expected,State::Ready);}
    }
    // No partial success after audio stalls or a missed block. Raw data expires
    // even if the host disconnects; clearing is outside the input callback.
    bool poll(uint64_t now) {
        if(state()==State::Recording && now>=deadline_)state_=State::Failed;
        if(state()!=State::Empty && now>=expires_) {clear();return true;}
        return false;
    }
    void clear() {
        state_=State::Empty;
        std::lock_guard<std::mutex> lock(mutex_);
        state_=State::Empty; // A callback already holding the lock has now exited.
        if(data_) {volatile int16_t* p=data_;for(size_t i=0;i<capacity_;++i)p[i]=0;}
        count_=target_=0;
    }
    State state() const {return state_.load();}
    void missed_block() {State expected=State::Recording;state_.compare_exchange_strong(expected,State::Failed);}
    size_t size() const {return state()==State::Ready?count_.load():0;}
    size_t recorded_samples() const {return count_.load();}
    const int16_t* data() const {return state()==State::Ready?data_:nullptr;}
 private:
    int16_t* data_;size_t capacity_,target_=0;std::atomic<size_t> count_{0};
    uint64_t expires_=0,deadline_=0;std::atomic<State> state_{State::Empty};
    std::mutex mutex_;
};
}
