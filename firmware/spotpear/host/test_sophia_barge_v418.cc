// The AEC backend is a deterministic stub: this tests framing/allocation/latch
// contracts, not acoustic suppression or human wake-word recognition.
#include <cassert>
#include <cstdlib>
#include <cstdint>
#include <cstdio>
#include <string>
#include <vector>
#include "host_barge_wake.h"

static int allocations=0,fail_allocation=-1,alloc_attempts=0;
static bool create_failure=false;
static int requested_chunk=512;
static int handles=0;
static aec_config_t captured{};
aec_handle_t* aec_create_from_config(aec_config_t* config) {
    captured=*config;
    if(create_failure)return nullptr;
    ++handles;return new aec_handle_t{};
}
int aec_get_chunksize(const aec_handle_t*){return requested_chunk;}
void aec_process(const aec_handle_t*,int16_t* mic,int16_t* ref,int16_t* out) {
    for(unsigned i=0;i<512;++i)out[i]=mic[i]-ref[i];
}
void aec_destroy(aec_handle_t* handle){--handles;delete handle;}
void* heap_caps_aligned_alloc(size_t alignment,size_t size,unsigned) {
    if(alloc_attempts++==fail_allocation)return nullptr;
    void* p=nullptr;if(posix_memalign(&p,alignment,size))return nullptr;
    ++allocations;return p;
}
void heap_caps_free(void* p){if(p){--allocations;std::free(p);}}

static void framing() {
    gobot_host::PlaybackReferenceAec aec;
    assert(aec.Initialize(true,2));assert(aec.Ready());assert(aec.Initialize(true,2));
    assert(captured.mic_num==1 && captured.ref_num==1 && captured.out_num==1);
    assert(captured.sample_rate==16000 && captured.filter_length==4);
    assert(captured.mode==AEC_MODE_FD_LOW_COST && captured.nlp_level==AEC_NLP_LEVEL_AGGR);
    assert(allocations==3 && handles==1);
    const int16_t* out=nullptr;uint64_t start=999;
    for(unsigned block=0;block<32;++block) {
        int16_t stereo[320];
        for(unsigned i=0;i<160;++i){stereo[2*i]=block*160+i+100;stereo[2*i+1]=100;}
        assert(aec.Feed(7,block*160,stereo,160,start,out));
        if(out) {
            assert(start==(aec.Frames()-1)*512);
            for(unsigned i=0;i<512;++i)assert(out[i]==static_cast<int16_t>(start+i));
        }
    }
    assert(aec.Frames()==10 && aec.ReferenceFrames()==10);
    int16_t zeros[320]{};
    // A discontinuity never completes a frame using pre-gap samples.
    assert(aec.Feed(7,9000,zeros,160,start,out) && !out);
    assert(aec.Feed(7,9160,zeros,160,start,out) && !out);
    assert(aec.Feed(7,9320,zeros,160,start,out) && !out);
    assert(aec.Feed(7,9480,zeros,160,start,out) && out && start==9000);
    // Capture epochs also cut partial-frame history.
    assert(aec.Feed(8,50,zeros,160,start,out) && !out);
    aec.Reset();
    for(unsigned n=0;n<4;++n)assert(aec.Feed(8,1000+n*160,zeros,160,start,out));
    assert(out && start==1000);
    assert(aec.Frames()==12 && aec.ReferenceFrames()==10);
    assert(!aec.Feed(0,0,zeros,160,start,out) && !out);
    assert(!aec.Feed(8,0,nullptr,160,start,out) && !out);
    assert(!aec.Feed(8,0,zeros,161,start,out) && !out);
}

static void allocation_failure() {
    {gobot_host::PlaybackReferenceAec no_ref;assert(!no_ref.Initialize(false,2));assert(!no_ref.Ready());}
    {gobot_host::PlaybackReferenceAec mono;assert(!mono.Initialize(true,1));assert(!mono.Ready());}
    create_failure=true;
    {gobot_host::PlaybackReferenceAec failed;assert(!failed.Initialize(true,2));assert(!failed.Initialize(true,2));}
    create_failure=false;requested_chunk=256;
    {gobot_host::PlaybackReferenceAec wrong;assert(!wrong.Initialize(true,2));}
    requested_chunk=512;
    for(int fail=0;fail<3;++fail) {
        fail_allocation=fail;alloc_attempts=0;
        {gobot_host::PlaybackReferenceAec failed;assert(!failed.Initialize(true,2));assert(!failed.Ready());
            const int16_t* out=reinterpret_cast<const int16_t*>(1);uint64_t start=0;int16_t pcm[320]{};
            assert(!failed.Feed(1,0,pcm,160,start,out) && !out);}
        assert(allocations==0 && handles==0);
    }
    fail_allocation=-1;
}

static void latch() {
    gobot_host::InterruptLatch latch;
    assert(!latch.Pending() && !latch.Expired(8000));
    assert(!latch.Begin(nullptr,10,true));assert(!latch.Begin("",10,true));
    assert(!latch.Begin("bad\"id",10,true));
    assert(!latch.Begin(std::string(81,'x').c_str(),10,true));
    assert(latch.Begin("sophia-7",100,true));
    assert(latch.Pending() && latch.Listen());
    assert(!latch.Begin("touch-8",110,true));
    assert(!latch.Complete("sophia-6","listening"));
    assert(!latch.Complete("sophia-7","speaking"));
    assert(!latch.Complete("sophia-7",nullptr));
    assert(!latch.Expired(99) && !latch.Expired(8099) && latch.Expired(8100));
    assert(latch.Complete("sophia-7","listening"));
    assert(!latch.Pending() && !latch.Complete("sophia-7","listening"));
    assert(latch.Begin("touch-8",9000,false) && !latch.Listen());
    assert(latch.Complete("touch-8","ready"));
    assert(latch.Begin("touch-9",0,true));latch.Reset();assert(!latch.Pending());
}

int main() {
    framing();assert(allocations==0 && handles==0);
    allocation_failure();latch();
    std::puts("PASS original capture clock / partial AEC frames / allocation failure / correlated interrupt latch / watchdog");
}
