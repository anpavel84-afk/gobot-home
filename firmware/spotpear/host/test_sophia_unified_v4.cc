#include <sophia_host_capture.h>
#include <host_rc1_state.h>
#include <host_output_receipts.h>
#include <cassert>
#include <iostream>
#include <vector>

int main() {
    gobot_host::CapturePacker capture;
    std::vector<int16_t> input(160);
    std::vector<gobot_host::CapturePosition> positions;
    std::vector<int16_t> captured;
    auto emit=[&](const auto& position,const int16_t* pcm){
        positions.push_back(position);captured.insert(captured.end(),pcm,pcm+960);
    };
    capture.Reset(4);
    for(int block=0;block<13;++block) {
        for(int i=0;i<160;++i)input[i]=block*160+i;
        assert(capture.Feed(input.data(),input.size(),emit));
    }
    assert(positions.size()==2 && capture.NextSample()==2080);
    for(size_t i=0;i<captured.size();++i)assert(captured[i]==int(i));
    assert(positions[0].epoch==4 && positions[0].sample_start==0 && positions[0].frame_id==0);
    assert(positions[1].sample_start==960 && positions[1].sample_count==960);
    capture.Reset(5); // mute/reconnect never concatenates the previous partial frame
    std::fill(input.begin(),input.end(),-9);
    for(int i=0;i<6;++i)assert(capture.Feed(input.data(),160,emit));
    assert(positions.back().epoch==5 && positions.back().frame_id==0 && positions.back().sample_start==0);
    for(size_t i=1920;i<2880;++i)assert(captured[i]==-9);
    assert(!capture.Feed(input.data(),0,emit));
    assert(!capture.Feed(input.data(),961,emit));
    capture.Reset(0); // cold task restart must not retain the static packer's epoch
    assert(capture.Epoch()==0 && capture.NextSample()==0);
    assert(!capture.Feed(input.data(),160,emit));
    capture.Reset(6);
    const auto previous_frames=positions.size();
    for(int i=0;i<6;++i)assert(capture.Feed(input.data(),160,emit));
    assert(positions.size()==previous_frames+1 && positions.back().epoch==6 &&
           positions.back().frame_id==0 && positions.back().sample_start==0);

    gobot_host::Rc1Stream stream;
    assert(stream.Ready("session","epoch"));
    assert(!stream.OutputStart("session","epoch","p",1,0,true));
    assert(stream.OutputStart("session","epoch","p",0,0,true));
    assert(!stream.ConsumeBinary());
    assert(stream.OutputMetadata("session","epoch","p",0,0,0,1440));
    assert(!stream.OutputMetadata("session","epoch","p",0,1,1440,1440));
    assert(stream.ConsumeBinary());
    assert(!stream.OutputEnd("session","epoch","p",0,2));
    assert(stream.PlaybackStarted("p",0));
    assert(!stream.PlaybackDrained("p",0));
    assert(stream.OutputEnd("session","epoch","p",0,1));
    assert(stream.PlaybackDrained("p",0));
    assert(!stream.PlaybackDrained("p",0));
    assert(stream.OutputStart("session","epoch","p2",0,0,true));
    assert(stream.OutputMetadata("session","epoch","p2",0,0,0,1440));
    assert(stream.CancelCurrent("session","epoch","p2",0));
    assert(stream.OutputEpoch()==1 && !stream.ConsumeBinary());
    assert(stream.CancelCurrent("session","epoch","p2",0)); // idempotent exact retry
    assert(!stream.CancelCurrent("session","epoch","wrong",0));
    assert(!stream.OutputStart("session","epoch","p3",0,0,true));
    assert(stream.OutputStart("session","epoch","p3",1,0,true));
    assert(!stream.CancelCurrent("session","epoch","p2",0)); // stale owner cannot stop new owner

    gobot_host::Rc1Stream raced;
    assert(raced.Ready("session","epoch"));
    assert(raced.OutputStart("session","epoch","last",0,1));
    assert(raced.OutputMetadata("session","epoch","last",0,0,0,1440));
    assert(raced.ConsumeBinary());assert(raced.PlaybackStarted("last",0));
    assert(raced.OutputEnd("session","epoch","last",0,1));
    assert(raced.PlaybackDrained("last",0));
    assert(raced.CancelCurrent("session","epoch","last",0)); // stop crossing final DMA receipt
    assert(raced.CancelCurrent("session","epoch","last",0));
    assert(raced.OutputEpoch()==1);

    gobot_host::OutputReceipts receipts;
    std::vector<std::string> heard;
    uint32_t actual_dma=100;
    auto poll=[&]{receipts.Poll([&](uint32_t fence){
        return static_cast<int32_t>(actual_dma-fence)>=0;
    },[&](const auto& segment){heard.push_back(segment.id);});};
    assert(receipts.Segment("resp_1:0",1600));
    assert(receipts.Written(0,107));
    actual_dma=200;poll();assert(heard.empty()); // first packet does not cover sentence end
    assert(receipts.Written(1,207));poll();assert(heard.empty());
    actual_dma=207;poll();assert(heard.size()==1 && heard[0]=="resp_1:0");
    assert(receipts.Segment("resp_1:1",2800)); // metadata may follow the output callback
    poll();assert(heard.size()==2);
    assert(receipts.Segment("resp_1:2",2881));
    assert(!receipts.Written(3,214)); // cannot pretend a missing decoded packet was played
    assert(receipts.Written(2,214));poll();assert(heard.size()==2);
    receipts.Reset();actual_dma=1000;poll();assert(heard.size()==2); // cancelled segment never acknowledged
    assert(gobot_host::wire_identifier("resp_ab-1"));
    assert(gobot_host::wire_identifier("resp_ab-1:2",true));
    assert(!gobot_host::wire_identifier("a\"b"));
    assert(!gobot_host::wire_identifier("a:2"));
    std::cout<<"capture-clock, ordered Opus, cancel epochs and DMA segment fences: PASS\n";
}
