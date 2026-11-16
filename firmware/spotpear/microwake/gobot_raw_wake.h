#pragma once
#include <cstddef>
#include <cstdint>
#include <string>
namespace gobot_raw_wake {
bool busy();
bool command(const std::string& line, bool idle, bool muted, uint64_t now);
bool touch(bool physical, bool hold, uint64_t now);
void feed(const int16_t* pcm,size_t n);
void missed_block();
void poll(uint64_t now);
const char* label();
const char* detail();
}
