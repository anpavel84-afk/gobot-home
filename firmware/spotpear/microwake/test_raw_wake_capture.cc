#include "raw_wake_capture.h"
#include <cassert>
#include <vector>
int main() {
    using raw_wake::State;
    std::vector<int16_t> memory(16000*15,123);raw_wake::Capture c(memory.data(),memory.size());
    int16_t block[160];for(int i=0;i<160;++i)block[i]=i-80;
    c.feed(block,160);assert(c.state()==State::Empty);
    assert(!c.arm(14,0) && !c.arm(16,0));assert(c.arm(15,0));
    assert(!c.start(false,1));assert(c.start(true,1));assert(!c.arm(15,1));
    for(int i=0;i<1500;++i)c.feed(block,160);
    assert(c.state()==State::Ready && c.size()==240000);
    for(size_t i=0;i<c.size();++i)assert(c.data()[i]==block[i%160]);
    c.feed(block,160);assert(c.size()==240000);
    assert(c.poll(120000));assert(c.state()==State::Empty);
    for(auto v:memory)assert(v==0);
    assert(c.arm(15,200000) && c.start(true,200001));
    c.feed(block,160);c.poll(217001);assert(c.state()==State::Failed && !c.data());
    c.clear();assert(c.arm(15,300000));assert(!c.start(true,420000));
    c.clear();for(auto v:memory)assert(v==0);
    assert(c.arm(15,500000) && c.start(true,500001));
    c.feed(block,160);c.missed_block();assert(c.state()==State::Failed && c.size()==0);
    c.clear();
    assert(c.release_storage()==memory.data());assert(!c.arm(15,600000));
    assert(c.attach(memory.data(),memory.size()) && c.arm(15,600000));
    c.clear();
}
