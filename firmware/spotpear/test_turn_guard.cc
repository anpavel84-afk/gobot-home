#include "gobot_turn_guard.h"
#include <cassert>
#include <cstdio>
using namespace gobot;
int main(){
 int checks=0;
 auto expect=[&](bool b){assert(b);++checks;};
 TurnGuard t;expect(!t.UploadAllowed());expect(t.Begin(1000));expect(!t.Begin(1001));
 expect(t.Poll(15999,false,true)==Action::None);expect(t.Poll(16000,false,true)==Action::Timeout);
 t.End(16000);expect(!t.Begin(16999));expect(t.Begin(17000));expect(t.Connected(17100));
 expect(t.UploadAllowed());expect(t.Poll(20000,true,true)==Action::None);
 expect(t.Poll(20799,false,true)==Action::None);expect(t.Poll(20800,false,true)==Action::StopCapture);
 expect(!t.UploadAllowed());expect(t.GetPhase()==Phase::Waiting);expect(!t.Connected(20900));
 expect(!t.TtsStop(20900));expect(t.TtsStart(21000));expect(!t.UploadAllowed());
 expect(t.TtsStop(22000));expect(t.Poll(22001,false,false)==Action::None);
 expect(t.Poll(22002,false,true)==Action::Finish);t.End(22002);expect(!t.UploadAllowed());
 expect(!t.TtsStart(24000));expect(t.Begin(25000));expect(t.Connected(25100));
 expect(t.Poll(31100,false,true)==Action::Finish);t.End(31100);
 expect(t.Begin(33000));expect(t.Connected(33000));expect(t.Poll(58000,true,true)==Action::StopCapture);
 expect(t.Poll(123000,false,true)==Action::Timeout);t.End(123000);
 expect(t.Begin(124000));expect(t.Connected(124000));
 expect(t.Poll(124100,true,true)==Action::None);expect(t.Poll(124900,false,true)==Action::StopCapture);
 expect(t.TtsStart(125000));expect(t.Poll(305000,false,true)==Action::Timeout);
 t.End(305000);expect(t.Begin(306000));expect(t.Connected(306000));
 expect(t.Poll(306100,true,true)==Action::None);expect(t.Poll(306900,false,true)==Action::StopCapture);
 expect(t.TtsStart(307000));expect(t.TtsStop(308000));expect(t.Poll(316000,false,false)==Action::Timeout);
 std::printf("TURN_GUARD_PASS checks=%d\n",checks);
}
