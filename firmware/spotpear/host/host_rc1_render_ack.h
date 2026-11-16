#pragma once
// Native LVGL refresh receipt. This is after the LVGL refresh/flush callback,
// NOT proof that a person saw the LCD; human validation is separate.
#include "touch_lcd.h"
#include <functional>
#include <utility>
namespace gobot_host {
inline bool OnNextNativeRefresh(std::function<void()>&& notify) {
    auto* view=Board::GetInstance().GetDisplay();
    DisplayLockGuard guard(view);
    if(!guard)return false;
    auto* display=lv_display_get_default();
    if(!display)return false;
    static lv_display_t* installed=nullptr;
    static std::function<void()> pending;
    if(pending)return false; // One hardware receipt at a time.
    if(installed && installed!=display)return false;
    if(!installed) {
        lv_display_add_event_cb(display,[](lv_event_t*) {
            if(pending) {
                auto finished=std::move(pending);
                pending={};
                finished(); // Only schedules work; never calls WSS from LVGL.
            }
        },LV_EVENT_REFR_READY,nullptr);
        installed=display;
    }
    pending=std::move(notify);
    return true;
}
}
