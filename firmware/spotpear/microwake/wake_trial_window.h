#pragma once
#include <cstdint>
#include <limits>
namespace gobot {
// Main-task-only local admission. This does NOT replace the server budget/ACL.
class WakeTrialWindow {
 public:
    bool Arm(uint64_t now,unsigned seconds,unsigned attempts) {
        if(!seconds||seconds>600||!attempts||attempts>3||
           now>std::numeric_limits<uint64_t>::max()-seconds*1000ULL||
           (armed_&&now<until_))return false;
        armed_=true;until_=now+seconds*1000ULL;left_=attempts;return true;
    }
    bool Active(uint64_t now) const{return armed_&&now<until_&&left_>0;}
    bool Claim(uint64_t now){if(!Active(now))return false;--left_;return true;}
    unsigned Remaining(uint64_t now)const{return Active(now)?left_:0;}
    void Cancel(){armed_=false;until_=0;left_=0;}
 private:
    uint64_t until_=0;unsigned left_=0;bool armed_=false;
};
}
