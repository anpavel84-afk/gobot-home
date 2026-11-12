#include "kws_frontend.h"
#include <cassert>
#include <cstdio>

int main() {
    gobot::KeywordFeatures frontend;
    std::array<int16_t,256> pcm{};
    for (unsigned i=0; i<pcm.size(); ++i) pcm[i] = int((i*31337+29)%65536)-32768;
    gobot::KeywordFeatures::Frame expected = {
        -87,-100,-100,-100,-1,-13,-100,-42,-15,-100,-24,-100,-31,-42,-40,-36,-37,-35,-30,0
    };
    std::array<gobot::KeywordFeatures::Frame,18> frames;
    for (auto& frame:frames) {
        assert(frontend.Extract(pcm.data(),frame)>1000);
        assert(frame==expected);
    }
    gobot::KeywordFeatures::Weights weights{};
    weights[0]=1; weights.back()=0.5f;
    assert(std::abs(frontend.Score(frames.data(),18,weights)+.37f)<.0001f);
    assert(!std::isfinite(frontend.Score(frames.data(),7,weights)));
    assert(!std::isfinite(frontend.Score(frames.data(),86,weights)));
    std::printf("KWS_FRONTEND_PASS workspace=%zu\n",sizeof(frontend));
}
