#pragma once
#include "touch_screen.h"
#include "board.h"
#include "display.h"
#include <esp_heap_caps.h>

namespace touchui {
inline void Render(const Page& page) {
    static Page last;
    static lv_obj_t* image=nullptr;
    static lv_image_dsc_t descriptor{};
    static uint16_t* buffer=nullptr;
    if(image && page==last) return;
    auto* display=Board::GetInstance().GetDisplay();
    DisplayLockGuard lock(display);
    if(!buffer) buffer=static_cast<uint16_t*>(heap_caps_malloc(240*240*2,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
    if(!buffer) {ESP_LOGE("GoBotLCD","framebuffer allocation failed");return;}
    Screen(buffer).draw(page);
    if(!image) {
        descriptor.header.magic=LV_IMAGE_HEADER_MAGIC;
        descriptor.header.cf=LV_COLOR_FORMAT_RGB565;
        descriptor.header.w=descriptor.header.h=240;
        descriptor.header.stride=480;
        descriptor.data_size=240*480;
        descriptor.data=reinterpret_cast<uint8_t*>(buffer);
        image=lv_image_create(lv_layer_top());
        lv_image_set_src(image,&descriptor);
        lv_obj_center(image);
        ESP_LOGI("GoBotLCD","GOBOT_LCD atlas=1 size=240x240");
    }
    lv_obj_invalidate(image);
    last=page;
}
}
