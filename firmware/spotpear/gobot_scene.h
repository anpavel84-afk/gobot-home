#pragma once
#include <cJSON.h>
#include <cmath>
#include <cstring>
#include <string>

// Parse on the network callback. Pass only bounded owned values to the GUI task.
namespace gobot {
struct Scene {
    std::string title;
    std::string text;
    int remaining_ms = -1;
};
inline const char* String(const cJSON* root, const char* key, size_t max_bytes) {
    const auto* item = cJSON_GetObjectItemCaseSensitive(root, key);
    return cJSON_IsString(item) && item->valuestring && strlen(item->valuestring) <= max_bytes
        ? item->valuestring : nullptr;
}
inline bool ParseScene(const cJSON* root, Scene& scene) {
    if (!cJSON_IsObject(root)) return false;
    auto ns = String(root, "namespace", 16);
    auto cmd = String(root, "command", 32);
    auto version = cJSON_GetObjectItemCaseSensitive(root, "version");
    if (!ns || strcmp(ns, "gobot.ui") || !cmd || !cJSON_IsNumber(version)) return false;
    if (version->valuedouble == 1 && strcmp(cmd, "timer.start") == 0) {
        const auto* duration = cJSON_GetObjectItemCaseSensitive(root, "duration_ms");
        if (!cJSON_IsNumber(duration) || !(duration->valuedouble >= 1 && duration->valuedouble <= 86400000)) return false;
        scene.title = "Таймер";
        scene.remaining_ms = duration->valueint;
        return true;
    }
    if (version->valuedouble != 2 || strcmp(cmd, "presentation.show")) return false;
    auto title = String(root, "title", 320);
    auto text = String(root, "text", 960);
    auto type = String(root, "type", 40);
    if (!title || !type || !text) return false;
    scene.title = title;
    scene.text = text;
    if (!strcmp(type, "timer_widget")) {
        const auto* duration = cJSON_GetObjectItemCaseSensitive(root, "remaining_ms");
        if (!cJSON_IsNumber(duration) || !(duration->valuedouble >= 0 && duration->valuedouble <= 86400000)) return false;
        scene.remaining_ms = duration->valueint;
    }
    return true;
}
}
