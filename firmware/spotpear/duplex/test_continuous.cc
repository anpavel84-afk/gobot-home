#include "gobot_turn_guard.h"
#include <cassert>
int main(){
    gobot::TurnGuard turn;
    turn.Continuous(true);
    assert(turn.Begin(2000));
    assert(!turn.UploadAllowed());
    assert(turn.Connected(2100));
    assert(turn.UploadAllowed());
    // An interword pause never submits or ends a continuous Live session.
    assert(turn.Poll(10000,false,true)==gobot::Action::None);
    assert(turn.TtsStart(11000));
    assert(turn.UploadAllowed());
    assert(turn.Poll(12000,true,false)==gobot::Action::None);
    assert(turn.TtsStop(13000));
    assert(turn.UploadAllowed());
    assert(turn.TtsStart(14000));
    turn.End(15000);
    assert(!turn.UploadAllowed());
    assert(!turn.Begin(15100));
    assert(turn.Begin(17000));
}
