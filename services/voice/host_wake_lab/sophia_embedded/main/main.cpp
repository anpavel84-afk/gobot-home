/* HOST-B standalone: official Sophia model embedded in APP, no extra partition.
 * PCM input is synthetic silence here; A owns real ES8311/I2S fanout.
 * This tests compile/link/packing and demonstrates a callable real-PCM
 * interface. It is NOT an A RC1 firmware, does not open a microphone or
 * create a real local wake event on any running Spotpear.
 */
#include <cstddef>
#include <cstdint>
#include "esp_log.h"
#include "esp_heap_caps.h"
#include "esp_timer.h"
#include "embedded_sophia_engine.hpp"

static const char *TAG="SOPHIA_B_EMBED_POC";
static unsigned g_event_callbacks=0;
static void diagnostic_silence_event(const gobot_sophia::WakeEvidence& e,
                                      void *) {
    ++g_event_callbacks;
    ESP_LOGE(TAG,"UNEXPECTED_SILENCE_DETECTION epoch=%lu sample_end=%llu infer_us=%llu",
             static_cast<unsigned long>(e.epoch),
             static_cast<unsigned long long>(e.sample_end),
             static_cast<unsigned long long>(e.inference_duration_us));
}
extern "C" void app_main(void) {
    // Static to avoid putting the fixed 8 KiB PCM chunk buffer on task stack.
    static gobot_sophia::EmbeddedSophiaEngine engine;
    const auto internal_before=heap_caps_get_free_size(MALLOC_CAP_INTERNAL);
    const auto psram_before=heap_caps_get_free_size(MALLOC_CAP_SPIRAM);
    if(!engine.initialize()) {
        ESP_LOGE(TAG,"EMBEDDED_SOPHIA_MODEL_LOAD_FAILURE");
        return;
    }
    if(!engine.set_owner(gobot_sophia::WakeOwner::ESP_LOCAL_SOPHIA)) {
        ESP_LOGE(TAG,"EXCLUSIVE_WAKE_OWNER_SWITCH_REFUSED");return;
    }
    static int16_t zero_capture_frame[960]{};
    for(uint32_t n=0;n<100;++n){
        const auto when_us=static_cast<uint64_t>(esp_timer_get_time());
        const uint64_t start=static_cast<uint64_t>(n)*960;
        if(!engine.ingest_existing_pcm(7,start,zero_capture_frame,960,when_us,
                                       diagnostic_silence_event,nullptr)){
            ESP_LOGE(TAG,"PCM_SEQUENCE_ERROR frame=%lu",
                     static_cast<unsigned long>(n));
            break;
        }
    }
    ESP_LOGI(TAG,"EMBEDDED_SOPHIA_DIAGNOSTIC_ONLY zero_audio_samples=%u native_frames=%llu raw_wake=%u callbacks=%u",
             100u*960u,
             static_cast<unsigned long long>(engine.inference_frames()),
             engine.raw_detections(),g_event_callbacks);
    ESP_LOGI(TAG,"SILENCE_BENCH_ONLY total_infer_us=%llu init_us=%llu",
             static_cast<unsigned long long>(engine.total_infer_us()),
             static_cast<unsigned long long>(engine.init_time_us()));
    ESP_LOGI(TAG,"HEAP_DELTAS_RUNTIME_ONLY internal=%ld psram=%ld; MEASURED_ONLY_IF_EXECUTED_ON_AUTHORIZED_BOARD",
             static_cast<long>(internal_before-heap_caps_get_free_size(MALLOC_CAP_INTERNAL)),
             static_cast<long>(psram_before-heap_caps_get_free_size(MALLOC_CAP_SPIRAM)));
    engine.close();
    ESP_LOGW(TAG,"NO ESP32 INSTALLED. NO I2S/Opus/Brain/Flash. NO LIVE MIC.");
}