#include "sophia_pcm_tap.hpp"
#include <cassert>
#include <cstdint>

using namespace gobot_sophia;

int main() {
    ExclusiveWakeGate gate;
    assert(gate.owner()==WakeOwner::PLAN_STREAM);
    assert(gate.allow_plan_wake());
    assert(gate.switch_to(WakeOwner::ESP_LOCAL_SOPHIA));
    assert(!gate.allow_plan_wake());
    auto token=gate.generation();
    assert(gate.eligible_for_local_wake());
    assert(gate.accept_local_wake(token,512));
    assert(!gate.accept_local_wake(token,1024)); // duplicate
    assert(!gate.switch_to(WakeOwner::PLAN_STREAM)); // latched while pending
    gate.set_phase(DevicePhase::LISTENING);
    assert(!gate.switch_to(WakeOwner::PLAN_STREAM));
    gate.set_phase(DevicePhase::SPEAKING);
    assert(!gate.switch_to(WakeOwner::PLAN_STREAM));
    gate.set_phase(DevicePhase::STOPPING);
    assert(!gate.switch_to(WakeOwner::PLAN_STREAM));
    gate.set_phase(DevicePhase::MUTED);
    assert(!gate.switch_to(WakeOwner::PLAN_STREAM));
    gate.set_phase(DevicePhase::IDLE);
    gate.set_pending(true);
    assert(!gate.switch_to(WakeOwner::PLAN_STREAM));
    gate.set_pending(false);
    assert(gate.switch_to(WakeOwner::PLAN_STREAM));
    assert(gate.allow_plan_wake());
    assert(!gate.accept_local_wake(token,1536)); // source & generation
    gate.begin_new_audio_epoch();

    ContiguousMonoPcmTap tap(512);
    int16_t one_frame[960]{};
    unsigned native_chunks=0;
    uint64_t last_end=0;
    auto on_chunk=[&](const int16_t *p,size_t n,uint64_t end) {
        assert(p && n==512);
        assert(end>last_end);
        last_end=end;native_chunks++;
    };
    assert(tap.valid());
    assert(tap.feed(7,0,one_frame,960,on_chunk));
    assert(native_chunks==1 && last_end==512 && tap.pending_samples()==448);
    assert(tap.feed(7,960,one_frame,960,on_chunk));
    assert(native_chunks==3 && last_end==1536 && tap.pending_samples()==384);
    assert(!tap.feed(7,9999,one_frame,960,on_chunk));
    assert(tap.dropped_gaps()==1 && tap.pending_samples()==0);
    assert(!tap.feed(7,0,one_frame,961,on_chunk));
    assert(!ContiguousMonoPcmTap(4097).valid());
    // Restart after an independent audio epoch, NOT from stale samples.
    last_end=0;
    assert(tap.feed(8,0,one_frame,960,on_chunk));
    return 0;
}