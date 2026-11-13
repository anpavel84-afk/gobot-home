#pragma once
#include <cstddef>
#include <cstdint>

// feed, flush and reset run on the existing audio input task only.
namespace gobot_mww {
bool feed(const int16_t* mono, size_t count);
void reset();
void report();
void miss();
void suspended();
bool qualified();
bool consume_overflow();
void retain(const int16_t* pcm, size_t count);
size_t take(int16_t* pcm, size_t limit);
}
