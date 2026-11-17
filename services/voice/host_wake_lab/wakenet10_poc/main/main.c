/*
 * GoBot HOST-B isolated WakeNet10 RU ENGINE proof-of-concept.
 * Model: OFFICIAL "wn10_ru_privetesp" for "Привет ESP", NOT "Моника".
 *
 * This application intentionally has no I2S, ES8311, Wi-Fi, network, Brain,
 * production gateway or NVS modifications. It benchmarks official engine
 * initialization and PCM16 mono 16 kHz synthetic zeros if ever installed on
 * a SEPARATE authorized development board (NOT the user's Spotpear).
 *
 * BUILT does NOT imply measured MCU runtime, sound quality or Monika weights.
 */
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include "esp_log.h"
#include "esp_heap_caps.h"
#include "esp_timer.h"
#include "model_path.h"
#include "esp_wn_iface.h"
#include "esp_wn_models.h"

static const char *TAG = "GOBOT_WN10_RU_POC";
#define DEMO_MODEL "wn10_ru_privetesp"
#define EXPECTED_RATE 16000
#define MAX_SAFE_CHUNK_SAMPLES 4096
#define DRY_FEED_COUNT 100

void app_main(void)
{
    ESP_LOGW(TAG, "ENGINE DEMO ONLY: %s means Privet ESP; NOT MONIKA", DEMO_MODEL);
    size_t internal_before = heap_caps_get_free_size(MALLOC_CAP_INTERNAL);
    size_t psram_before = heap_caps_get_free_size(MALLOC_CAP_SPIRAM);
    srmodel_list_t *models = esp_srmodel_init("model");
    if (!models) {
        ESP_LOGE(TAG, "MODEL_PARTITION_NOT_FOUND: a dedicated model partition is required");
        return;
    }
    char *selected = esp_srmodel_filter(models, ESP_WN_PREFIX, NULL);
    if (!selected || strcmp(selected, DEMO_MODEL) != 0) {
        ESP_LOGE(TAG, "ONLY_OFFICIAL_RUSSIAN_DEMO_ALLOWED, got %s",
                 selected ? selected : "(none)");
        esp_srmodel_deinit(models);
        return;
    }
    esp_wn_iface_t *iface = (esp_wn_iface_t *)esp_wn_handle_from_name(selected);
    if (!iface) {
        ESP_LOGE(TAG, "WAKENET10_INTERFACE_NOT_AVAILABLE");
        esp_srmodel_deinit(models);
        return;
    }
    /* DET_MODE_90 is Espressif's single-microphone 16-kHz WakeNet10 mode. */
    int64_t init_start_us = esp_timer_get_time();
    model_iface_data_t *model = iface->create(selected, DET_MODE_90);
    int64_t init_us = esp_timer_get_time() - init_start_us;
    if (!model) {
        ESP_LOGE(TAG, "MODEL_CREATE_FAILED");
        esp_srmodel_deinit(models);
        return;
    }
    int rate = iface->get_samp_rate(model);
    int channel_count = iface->get_channel_num(model);
    int chunk = iface->get_samp_chunksize(model);
    if (rate != EXPECTED_RATE || channel_count != 1 ||
        chunk <= 0 || chunk > MAX_SAFE_CHUNK_SAMPLES) {
        ESP_LOGE(TAG, "UNSAFE_PCM_CONTRACT rate=%d channels=%d chunk=%d",
                 rate, channel_count, chunk);
        iface->destroy(model);
        esp_srmodel_deinit(models);
        return;
    }
    int16_t *pcm = (int16_t *)heap_caps_calloc(
        (size_t)chunk, sizeof(int16_t), MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
    if (!pcm) {
        ESP_LOGE(TAG, "PCM_ALLOCATION_FAILED");
        iface->destroy(model);
        esp_srmodel_deinit(models);
        return;
    }
    size_t internal_now = heap_caps_get_free_size(MALLOC_CAP_INTERNAL);
    size_t psram_now = heap_caps_get_free_size(MALLOC_CAP_SPIRAM);
    ESP_LOGI(TAG, "MODEL_INIT_OK model=%s idf_target=esp32s3 rate=%d mic_channels=%d chunk_samples=%d init_ms=%.2f",
             DEMO_MODEL, rate, channel_count, chunk, (double)init_us / 1000.0);
    ESP_LOGI(TAG, "MEMORY_DELTA_OWN_RUNTIME internal=%d bytes psram=%d bytes (includes model plus PCM buffer)",
             (int)(internal_before - internal_now), (int)(psram_before - psram_now));
    int64_t work_us = 0;
    int detections = 0;
    for (int n = 0; n < DRY_FEED_COUNT; ++n) {
        int64_t t0 = esp_timer_get_time();
        int result = iface->detect(model, pcm);
        work_us += esp_timer_get_time() - t0;
        if (result == WAKENET_DETECTED) {
            ++detections;
            ESP_LOGW(TAG, "ZERO_INPUT_UNEXPECTED_WAKE_DETECTED frame=%d", n);
        }
    }
    double audio_ms = 1000.0 * DRY_FEED_COUNT * chunk / rate;
    ESP_LOGI(TAG, "SYNTHETIC_ZERO_PCM_FRAMES=%d audio_ms=%.1f mean_detect_us=%.1f one_core_cpu_estimate_pct=%.2f zero_speech_events=%d",
             DRY_FEED_COUNT, audio_ms, (double)work_us / DRY_FEED_COUNT,
             (double)work_us * 100.0 / (audio_ms * 1000.0), detections);
    heap_caps_free(pcm);
    iface->destroy(model);
    esp_srmodel_deinit(models);
    ESP_LOGI(TAG, "POC_DONE: no microphone, no network, no production wake changes");
}
