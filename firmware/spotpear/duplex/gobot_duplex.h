#pragma once
#include <atomic>
#include <algorithm>
#include <cmath>
#include <cstdint>
#include "esp_log.h"
#include "esp_timer.h"
namespace duplex_probe {
inline std::atomic<int64_t> began{0};
inline std::atomic<unsigned> raw_frames{},output_frames{},vad_frames{},read_errors{},write_errors{};
inline std::atomic<uint64_t> mic_power{},ref_power{},clean_power{};
inline std::atomic<unsigned> mic_peak{},ref_peak{},clean_peak{};
inline bool active(){auto t=began.load();return t && esp_timer_get_time()-t<11000000;}
inline void start(){
    raw_frames=output_frames=vad_frames=read_errors=write_errors=0;
    mic_power=ref_power=clean_power=0;mic_peak=ref_peak=clean_peak=0;
    began=esp_timer_get_time();
}
inline void raw(const int16_t* data,size_t n){
    if(!active())return;
    uint64_t m=0,r=0;unsigned mp=0,rp=0;
    for(size_t i=0;i+1<n;i+=2){
        int a=data[i],b=data[i+1];m+=int64_t(a)*a;r+=int64_t(b)*b;
        mp=std::max(mp,unsigned(std::abs(a)));rp=std::max(rp,unsigned(std::abs(b)));
    }
    mic_power+=m;ref_power+=r;mic_peak=mp;ref_peak=rp;++raw_frames;
}
inline void processed(const int16_t* data,size_t n,bool vad){
    if(!active())return;
    uint64_t power=0;unsigned peak=0;
    for(size_t i=0;i<n;++i){int a=data[i];power+=int64_t(a)*a;peak=std::max(peak,unsigned(std::abs(a)));}
    clean_power+=power;clean_peak=peak;++output_frames;if(vad)++vad_frames;
}
inline void report(){
    ESP_LOGI("duplex","GOBOT_DUPLEX active=%d raw=%u clean=%u vad=%u mic_power=%llu ref_power=%llu clean_power=%llu mic_peak=%u ref_peak=%u clean_peak=%u read_errors=%u write_errors=%u",
        active(),raw_frames.load(),output_frames.load(),vad_frames.load(),
        (unsigned long long)mic_power.load(),(unsigned long long)ref_power.load(),(unsigned long long)clean_power.load(),
        mic_peak.load(),ref_peak.load(),clean_peak.load(),read_errors.load(),write_errors.load());
}
}
