#include "wake_trial_window.h"
#include <cassert>
#include <limits>
int main(){
    gobot::WakeTrialWindow window;
    assert(!window.Active(0)&&!window.Claim(0));
    assert(!window.Arm(0,601,3)&&!window.Arm(0,600,4));
    assert(window.Arm(10,600,3));assert(window.Claim(11));
    assert(window.Remaining(11)==2);
    assert(!window.Arm(12,600,3)); // Duplicate arm cannot restore a spent attempt.
    assert(window.Claim(13)&&window.Claim(14)&&!window.Claim(15));
    assert(!window.Active(15)&&!window.Arm(16,600,3));
    assert(window.Arm(600010,1,1));assert(!window.Active(601010));
    assert(window.Arm(601011,1,1));window.Cancel();assert(!window.Active(601012));
    assert(!window.Arm(std::numeric_limits<uint64_t>::max(),600,3));
}
