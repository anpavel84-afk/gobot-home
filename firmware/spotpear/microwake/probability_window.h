#pragma once
#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
namespace gobot {
template<size_t N> class ProbabilityWindow {
    static_assert(N>=1 && N<=32,"Bounded KWS probability history");
 public:
    ProbabilityWindow(uint8_t cutoff,size_t warmup):cutoff_(cutoff),warmup_(std::max(N,warmup)){}
    bool Push(uint8_t value){
        sum_-=values_[position_];values_[position_]=value;sum_+=value;
        position_=(position_+1)%N;if(calls_<warmup_)++calls_;
        return calls_>=warmup_ && sum_>=unsigned(cutoff_)*N;
    }
    void Reset(){values_.fill(0);position_=calls_=sum_=0;}
    bool Warm() const{return calls_>=warmup_;}
 private:
    std::array<uint8_t,N> values_{};unsigned sum_=0;size_t position_=0,calls_=0;
    uint8_t cutoff_;size_t warmup_;
};
}
