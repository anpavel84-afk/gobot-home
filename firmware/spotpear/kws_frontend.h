#pragma once
// Embedded frontend for the experimental Russian linear classifier. Mono PCM16 / 16 kHz.
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>

namespace gobot {
class KeywordFeatures {
public:
    static constexpr int kSamples = 256, kBands = 20, kFrames = 85, kSteps = 20;
    using Frame = std::array<int8_t, kBands>;
    using Weights = std::array<float, kSteps*kBands + 1>;
    KeywordFeatures() {
        constexpr float pi = 3.14159265358979323846f;
        for (int i = 0; i < kSamples; ++i) {
            window_[i] = 0.5f - 0.5f * std::cos(2*pi*i/(kSamples-1));
            if (i < kSamples/2) {
                cosine_[i] = std::cos(2*pi*i/kSamples);
                sine_[i] = -std::sin(2*pi*i/kSamples);
            }
        }
    }
    float Extract(const int16_t* pcm, Frame& result) {
        float energy = 0;
        imag_.fill(0);
        for (int i=0,j=0; i<kSamples; ++i) {
            float x = pcm[i];
            energy += x*x;
            real_[j] = x * window_[i];
            int bit = kSamples / 2;
            while (bit && (j & bit)) { j ^= bit; bit >>= 1; }
            j ^= bit;
        }
        for (int width=2; width<=kSamples; width*=2) {
            int half = width / 2;
            for (int i=0; i<kSamples; i+=width) {
                for (int j=0; j<half; ++j) {
                    int a=i+j, b=a+half, w=j*kSamples/width;
                    float r=cosine_[w]*real_[b]-sine_[w]*imag_[b];
                    float s=cosine_[w]*imag_[b]+sine_[w]*real_[b];
                    real_[b]=real_[a]-r; imag_[b]=imag_[a]-s;
                    real_[a]+=r; imag_[a]+=s;
                }
            }
        }
        constexpr int edges[] = {2,3,5,7,9,12,15,18,22,26,31,36,42,49,56,65,74,85,97,111,126};
        std::array<float,kBands> bands{};
        for (int b=0; b<kBands; ++b) {
            float sum=0;
            for (int i=edges[b]; i<edges[b+1]; ++i) sum+=real_[i]*real_[i]+imag_[i]*imag_[i];
            bands[b]=std::log(std::max(1.f,sum/(edges[b+1]-edges[b])));
        }
        float peak=*std::max_element(bands.begin(),bands.end());
        for (int b=0; b<kBands; ++b)
            result[b]=static_cast<int8_t>(std::nearbyint(10*std::max(-10.f,bands[b]-peak)));
        return std::sqrt(energy/kSamples);
    }
    // Caller supplies endpointed frames from a bounded local buffer.
    static float Score(const Frame* frames, int count, const Weights& weights) {
        if (count<8 || count>kFrames) return -INFINITY;
        float score = weights.back();
        for (int i=0; i<kSteps; ++i) {
            int frame=std::nearbyint(static_cast<double>(i)*(count-1)/(kSteps-1));
            for (int b=0; b<kBands; ++b)
                score += frames[frame][b]*weights[i*kBands+b]/100.f;
        }
        return score;
    }
private:
    std::array<float, kSamples> real_{}, imag_{}, window_{};
    std::array<float, kSamples/2> cosine_{}, sine_{};
};
}
