// Host capture of the exact RGB565 renderer used by the LCD. No device simulation.
#include "touch_screen.h"
#include <array>
#include <cstdio>

int main() {
    using namespace touchui;
    const Page pages[] = {{View::Ready}, {View::Listening}, {View::Thinking},
        {View::Speaking,0,0,true}, {View::Muted}, {View::Offline},
        {View::Weather,0,0,false,"21 °C","Солнечно"}, {View::Timer,0,0,false,"0:30","Таймер"}};
    std::array<uint16_t,240*240> pixels{};
    for (const Page& page : pages) {
        Screen(pixels.data()).draw(page);
        if (std::fwrite(pixels.data(),sizeof(uint16_t),pixels.size(),stdout) != pixels.size()) return 1;
    }
}
