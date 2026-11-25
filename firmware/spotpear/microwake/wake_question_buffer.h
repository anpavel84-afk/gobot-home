#pragma once
#include <algorithm>
#include <cstddef>
#include <cstdint>

// Single audio-task owner. Caller supplies PSRAM; no allocation/network here.
namespace gobot {
class WakeQuestionBuffer {
 public:
  void Attach(int16_t* memory,size_t capacity,size_t prefix) {
    data_=memory;capacity_=capacity;prefix_=std::min(prefix,capacity);Clear();
  }
  void Clear() {
    if(data_)std::fill(data_,data_+capacity_,0);
    count_=position_=read_=0;active_=failed_=false;
  }
  bool Observe(const int16_t* pcm,size_t n) {
    if(!data_||!prefix_||active_||failed_)return false;
    for(size_t i=0;i<n;++i) {
      data_[position_]=pcm[i];position_=(position_+1)%prefix_;
      count_=std::min(prefix_,count_+1);
    }
    return true;
  }
  bool Activate() {
    if(!data_||active_||failed_)return false;
    if(count_==prefix_)std::rotate(data_,data_+position_,data_+count_);
    active_=true;read_=0;return true;
  }
  bool Append(const int16_t* pcm,size_t n) {
    if(!active_||failed_||!data_)return false;
    if(n>capacity_-count_) {failed_=true;return false;}
    std::copy(pcm,pcm+n,data_+count_);count_+=n;return true;
  }
  size_t Take(int16_t* pcm,size_t limit) {
    if(!active_||failed_)return 0;
    const size_t n=std::min(limit,count_-read_);
    std::copy(data_+read_,data_+read_+n,pcm);
    std::fill(data_+read_,data_+read_+n,0);read_+=n;return n;
  }
  bool Failed() const {return failed_;}
  size_t Pending() const {return active_&&!failed_?count_-read_:0;}
 private:
  int16_t* data_=nullptr;
  size_t capacity_=0,prefix_=0,count_=0,position_=0,read_=0;
  bool active_=false,failed_=false;
};
}
