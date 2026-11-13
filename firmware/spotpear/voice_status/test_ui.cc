#include "touch_screen.h"
#include "gobot_turn_guard.h"
#include <cassert>
#include <cstdio>
#include <cstdint>
void image(const char* path,touchui::Page p) {
    uint16_t pixels[240*240]{};
    touchui::Screen screen(pixels);screen.draw(p);
    auto file=fopen(path,"wb");assert(file);fprintf(file,"P6\n240 240\n255\n");
    for(auto rgb:pixels) {unsigned char color[3]={uint8_t((rgb>>11)*255/31),uint8_t(((rgb>>5)&63)*255/63),uint8_t((rgb&31)*255/31)};fwrite(color,1,3,file);}
    fclose(file);
}
int main() {
    gobot::TurnGuard turn;turn.Continuous(true);assert(turn.Begin(1000));assert(turn.Connected(1100));
    turn.Continuous(false);assert(turn.Submit(true));assert(turn.GetPhase()==gobot::Phase::Waiting);
    assert(turn.TtsStart(2000));assert(turn.GetPhase()==gobot::Phase::Speaking);
    assert(turn.TtsStop(3000));assert(turn.GetPhase()==gobot::Phase::Draining);
    touchui::Page p;p.engine="A";p.view=touchui::View::Thinking;image("a-thinking.ppm",p);
    auto other=p;other.engine="B";assert(!(p==other));
    p.engine="B";p.view=touchui::View::Listening;image("b-listening.ppm",p);
    p.engine="A";p.view=touchui::View::Speaking;p.badge="0:30";image("a-timer-speaking.ppm",p);
    puts("Existing waiting controls and A/B render fixtures PASS");
}
