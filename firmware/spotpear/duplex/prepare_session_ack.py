"""Application-level acknowledgment before any paid voice leg; bounded USB media probe."""
from pathlib import Path
from prepare_duplex import change
def prepare(root):
    m=root/"main"
    for p in (root/"CMakeLists.txt",m/"gobot_build_info.h"):
        change(p,"0.4.1-dev-livekit","0.4.2-dev-session-ack")
    p=m/"application.cc"
    marker='                live_continuous_=ok && full;gobot_turn_.Continuous(live_continuous_);'
    change(p,marker,marker+'\n                ESP_LOGI(TAG,"GOBOT_SESSION continuous=%d phase=%d",live_continuous_,int(gobot_turn_.GetPhase()));\n                if(live_continuous_)protocol_->SendSessionReady();')
    marker='    } else if(line=="GOBOT_DUPLEX_BEGIN"'
    change(p,marker,'    } else if(line=="GOBOT_MEDIA_BEGIN" && !gobot_turn_.Active() && !gobot_muted_) {\n        duplex_armed_=false;StartGoBotTurn("diagnostic");\n    } else if(line=="GOBOT_DUPLEX_BEGIN"')
    p=m/"protocols/protocol.h"
    marker='    void SendPlaybackActivity(bool playing,bool input_active=false) {'
    change(p,marker,'    void SendSessionReady(){SendText(std::string("{\\\"type\\\":\\\"gobot_session_ready\\\",\\\"session_id\\\":\\\"")+session_id_+"\\\",\\\"continuous\\\":true}");}\n'+marker)
if __name__=="__main__":
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument("tree",type=Path)
    prepare(parser.parse_args().tree)
