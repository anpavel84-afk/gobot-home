#pragma once
#include <cJSON.h>
#include <esp_log.h>
#include <esp_timer.h>
#include <nvs.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <sys/time.h>
#include <unistd.h>
#include <cstdio>
#include <cstring>
#include <functional>
#include <string>
#include <utility>
#include "settings.h"
#include "gobot_build_info.h"

namespace gobot {
inline uint64_t NowMs() { return static_cast<uint64_t>(esp_timer_get_time()/1000); }
inline void InitializeClock() {
    timeval now{}; gettimeofday(&now,nullptr);
    if (now.tv_sec < GOBOT_BUILD_EPOCH) {
        timeval build_time{.tv_sec=GOBOT_BUILD_EPOCH,.tv_usec=0}; settimeofday(&build_time,nullptr);
    }
}
struct Enrollment { std::string url; std::string token; };
inline bool ValidEnrollment(const Enrollment& e) {
    if (e.url.rfind("wss://",0)!=0 || e.url.size()>240 || e.url.find('@')!=std::string::npos ||
        e.url.find_first_of("\r\n ?#")!=std::string::npos || e.token.size()<48 || e.token.size()>128) return false;
    for (unsigned char c:e.token) {
        if (!((c>='a'&&c<='z')||(c>='A'&&c<='Z')||(c>='0'&&c<='9')||c=='_'||c=='-')) return false;
    }
    // Initial bring-up is LAN-only. Do not leak the device token to a public endpoint.
    const bool lan=e.url.rfind("wss://192.168.",0)==0 || e.url.rfind("wss://10.",0)==0;
    const auto slash=e.url.find('/',6);
    return lan && slash!=std::string::npos && e.url.substr(slash)=="/xiaozhi/v1/";
}
inline bool DecodeEnrollment(const std::string& json, Enrollment& e) {
    cJSON* root=cJSON_ParseWithLength(json.data(),json.size());
    if (!cJSON_IsObject(root)) { cJSON_Delete(root); return false; }
    const cJSON *url=cJSON_GetObjectItemCaseSensitive(root,"url"), *token=cJSON_GetObjectItemCaseSensitive(root,"token");
    if (cJSON_IsString(url)&&cJSON_IsString(token)) {e.url=url->valuestring;e.token=token->valuestring;}
    cJSON_Delete(root); return ValidEnrollment(e);
}
inline bool LoadEnrollment(Enrollment& e) {
    Settings settings("gobot",false);
    return DecodeEnrollment(settings.GetString("enrollment"),e);
}
inline bool SaveEnrollment(const std::string& json) {
    Enrollment e; if (!DecodeEnrollment(json,e)) return false;
    // One NVS value: URL and token cannot come from different partial configurations.
    cJSON* root=cJSON_CreateObject();
    cJSON_AddStringToObject(root,"url",e.url.c_str()); cJSON_AddStringToObject(root,"token",e.token.c_str());
    char* normalized=cJSON_PrintUnformatted(root); cJSON_Delete(root);
    if (!normalized) return false;
    nvs_handle_t handle=0; esp_err_t err=nvs_open("gobot",NVS_READWRITE,&handle);
    if (err==ESP_OK) { err=nvs_set_str(handle,"enrollment",normalized); if(err==ESP_OK)err=nvs_commit(handle); nvs_close(handle); }
    cJSON_free(normalized); return err==ESP_OK;
}
inline void StartSerialConsole(std::function<void(std::string)> callback) {
    auto* cb=new std::function<void(std::string)>(std::move(callback));
    BaseType_t result=xTaskCreate([](void* argument) {
        auto* on_line=static_cast<std::function<void(std::string)>*>(argument);
        std::string line; line.reserve(1024); bool overflow=false;
        while(true) {
            char c=0; const int count=read(STDIN_FILENO,&c,1);
            if(count!=1) {vTaskDelay(pdMS_TO_TICKS(20));continue;}
            if(c=='\r'||c=='\n') {
                if(!overflow && line.rfind("GOBOT_",0)==0) (*on_line)(line);
                line.clear();overflow=false;
            } else if(!overflow) {
                if(line.size()>=1024) {line.clear();overflow=true;} else line.push_back(c);
            }
        }
    },"gobot_serial",4096,cb,1,nullptr);
    if(result!=pdPASS) {delete cb;ESP_LOGE("GoBot","GOBOT_CONSOLE_FAILED");}
}
}
