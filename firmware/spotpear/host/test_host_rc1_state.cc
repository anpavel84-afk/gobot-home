#include "host_rc1_state.h"
#include <cassert>
#include <iostream>
using gobot_host::Rc1Stream;

int main() {
    Rc1Stream state;
    assert(!state.IsReady());
    uint32_t sequence=0;
    assert(!state.SendPosition(10,sequence));
    assert(state.Ready("test-session", "epoch-1"));
    assert(!state.Ready("test-session","epoch-1"));
    assert(state.SendPosition(450,sequence)&&sequence==0);
    assert(state.SendPosition(451,sequence)&&sequence==1);
    assert(!state.SendPosition(453,sequence)); // Source gap never concealed.
    assert(!state.OutputStart("wrong","epoch-1","p1",0,2));
    assert(state.OutputStart("test-session","epoch-1","p1",0,2));
    assert(!state.OutputMetadata("test-session","epoch-1","p1",0,1,1440,1440));
    assert(state.OutputMetadata("test-session","epoch-1","p1",0,0,0,1440));
    assert(!state.OutputMetadata("test-session","epoch-1","p1",0,0,0,1440));
    assert(state.ConsumeBinary());
    assert(!state.ConsumeBinary());
    assert(state.PlaybackStarted("p1",0));
    assert(!state.PlaybackStarted("p1",0));
    assert(!state.PlaybackDrained("p1",0)); // OutputEnd not received.
    assert(state.OutputMetadata("test-session","epoch-1","p1",0,1,1440,1440));
    assert(state.ConsumeBinary());
    assert(!state.OutputEnd("test-session","epoch-1","p1",0,1));
    assert(state.OutputEnd("test-session","epoch-1","p1",0,2));
    assert(state.PlaybackDrained("p1",0));
    assert(!state.PlaybackDrained("p1",0));
    assert(!state.OutputStart("test-session","epoch-1","old",1,1));
    assert(state.Stop("test-session","epoch-1",1));
    assert(!state.Stop("test-session","epoch-1",1));
    assert(state.OutputStart("test-session","epoch-1","new",1,1));
    assert(!state.OutputMetadata("test-session","epoch-1","new",0,0,0,1440));
    state.Clear();
    assert(!state.Scope("test-session","epoch-1"));
    assert(state.Ready("new-session","new-epoch"));
    assert(state.SendPosition(10,sequence)&&sequence==0);
    std::cout<<"HOST_RC1_STATE_NATIVE_PASS"<<std::endl;
    return 0;
}
