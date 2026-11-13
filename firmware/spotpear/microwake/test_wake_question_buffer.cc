#include "wake_question_buffer.h"
#include <cassert>
#include <algorithm>
#include <iterator>
#include <cstdio>
int main() {
  int16_t memory[240]{},input[200]{},out[240]{};
  for(int i=0;i<200;++i)input[i]=i+1;
  gobot::WakeQuestionBuffer b;b.Attach(memory,240,40);
  assert(b.Observe(input,100));assert(b.Take(out,240)==0);
  assert(b.Activate());assert(!b.Activate());
  assert(b.Append(input+100,100));assert(b.Pending()==140);
  assert(b.Take(out,13)==13);assert(b.Take(out+13,240)==127);
  for(int i=0;i<140;++i)assert(out[i]==i+61);
  assert(b.Take(out,1)==0);b.Clear();assert(b.Pending()==0);
  assert(std::all_of(std::begin(memory),std::end(memory),[](int16_t s){return s==0;}));
  assert(b.Observe(input,12));assert(b.Activate());assert(b.Append(input+12,188));
  assert(b.Take(out,240)==200);for(int i=0;i<200;++i)assert(out[i]==i+1);
  b.Clear();assert(b.Observe(input,40));assert(b.Activate());
  assert(!b.Append(input,201));assert(b.Failed());assert(b.Take(out,240)==0);
  b.Clear();assert(!b.Failed()&&b.Take(out,240)==0);
  puts("wake_question_buffer: prefix, one-phrase order, bounds, zeroization, stale replay PASS");
}
