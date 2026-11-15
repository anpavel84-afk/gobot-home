#include "probability_window.h"
#include <cassert>
int main(){
    gobot::ProbabilityWindow<10> reference(231,68);
    for(int i=0;i<70;++i)assert(!reference.Push(0));
    for(int i=0;i<3;++i)assert(!reference.Push(255));
    for(int i=0;i<20;++i)assert(!reference.Push(0));
    for(int i=0;i<9;++i)assert(!reference.Push(255));
    assert(reference.Push(255));
    reference.Reset();for(int i=0;i<67;++i)assert(!reference.Push(255));
    assert(reference.Push(255));
    gobot::ProbabilityWindow<3> legacy(250,25);
    for(int i=0;i<24;++i)assert(!legacy.Push(255));
    assert(legacy.Push(255));legacy.Reset();assert(!legacy.Push(255));
}
