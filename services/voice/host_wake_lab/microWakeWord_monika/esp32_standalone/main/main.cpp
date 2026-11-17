/*
 * HOST-B CPU-trained Monika microWakeWord: ESP-IDF TFLite Micro code-only POC.
 * The model weights are a PRIVATE, not-yet-approved training candidate.
 *
 * No ES8311/I2S reader, WiFi, Opus, real microphone, Brain, personal data,
 * GPIO, serial/flash actions, or new production wake. Synthetic silence ONLY.
 * A real integrated HOST-A RC1 app must be designed/built separately.
 */
#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <cmath>

#include "esp_log.h"
#include "esp_heap_caps.h"
#include "esp_timer.h"
#include "tensorflow/lite/schema/schema_generated.h"
#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/micro/micro_mutable_op_resolver.h"
#include "tensorflow/lite/micro/micro_resource_variable.h"
#include "frontend.h"
#include "frontend_util.h"

extern const unsigned char model_bytes[] asm("_binary_monika_int8_tflite_start");

static const char *TAG="MWW_MONIKA_SANDBOX";
static const size_t kArenaBytes=192*1024;
static const size_t kVarBytes=4096;

extern "C" void app_main(void) {
    ESP_LOGW(TAG,"PRIVATE MONIKA INT8 MODEL FOR BENCHMARK ONLY, NOT ACOUSTICALLY ACCEPTED");
    const size_t before_int=heap_caps_get_free_size(MALLOC_CAP_INTERNAL);
    const size_t before_ps=heap_caps_get_free_size(MALLOC_CAP_SPIRAM);

    FrontendConfig cfg{};
    FrontendFillConfigWithDefaults(&cfg);
    cfg.window.size_ms=30;
    cfg.window.step_size_ms=10;
    cfg.filterbank.num_channels=40;
    cfg.filterbank.lower_band_limit=125;
    cfg.filterbank.upper_band_limit=7500;
    cfg.noise_reduction.smoothing_bits=10;
    cfg.noise_reduction.even_smoothing=0.025;
    cfg.noise_reduction.odd_smoothing=0.06;
    cfg.noise_reduction.min_signal_remaining=0.05;
    cfg.pcan_gain_control.enable_pcan=true;
    cfg.pcan_gain_control.strength=0.95;
    cfg.pcan_gain_control.offset=80;
    cfg.pcan_gain_control.gain_bits=21;
    cfg.log_scale.enable_log=true;
    cfg.log_scale.scale_shift=6;

    FrontendState f{};
    if (!FrontendPopulateState(&cfg,&f,16000)) {
        ESP_LOGE(TAG,"MICROFRONTEND_INIT_FAIL");
        return;
    }
    auto model=tflite::GetModel(model_bytes);
    if (!model || model->version()!=TFLITE_SCHEMA_VERSION) {
        ESP_LOGE(TAG,"TFLITE_SCHEMA_MISMATCH"); return;
    }
    static tflite::MicroMutableOpResolver<13> ops;
    if (ops.AddCallOnce()!=kTfLiteOk || ops.AddVarHandle()!=kTfLiteOk ||
        ops.AddReshape()!=kTfLiteOk || ops.AddReadVariable()!=kTfLiteOk ||
        ops.AddStridedSlice()!=kTfLiteOk || ops.AddConcatenation()!=kTfLiteOk ||
        ops.AddAssignVariable()!=kTfLiteOk || ops.AddConv2D()!=kTfLiteOk ||
        ops.AddFullyConnected()!=kTfLiteOk || ops.AddLogistic()!=kTfLiteOk ||
        ops.AddQuantize()!=kTfLiteOk || ops.AddDepthwiseConv2D()!=kTfLiteOk ||
        ops.AddSplitV()!=kTfLiteOk) {
        ESP_LOGE(TAG,"MISSING_TFLM_OPERATOR");return;
    }
    uint8_t *arena=(uint8_t *)heap_caps_aligned_alloc(16,kArenaBytes,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
    uint8_t *varmem=(uint8_t *)heap_caps_aligned_alloc(16,kVarBytes,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
    if (!arena || !varmem) { ESP_LOGE(TAG,"MEMORY_ALLOC_FAIL"); return; }
    auto allocator=tflite::MicroAllocator::Create(varmem,kVarBytes);
    auto vars=allocator?tflite::MicroResourceVariables::Create(allocator,20):nullptr;
    if (!vars) { ESP_LOGE(TAG,"RESOURCE_VAR_INIT_FAIL");return; }
    static tflite::MicroInterpreter interpreter(model,ops,arena,kArenaBytes,vars);
    if (interpreter.AllocateTensors()!=kTfLiteOk) {
        ESP_LOGE(TAG,"ALLOCATE_TENSORS_FAILED");return;
    }
    TfLiteTensor *in=interpreter.input(0),*out=interpreter.output(0);
    if (!in || !out || in->type!=kTfLiteInt8 || out->type!=kTfLiteUInt8 ||
        in->dims->size!=3 || in->dims->data[0]!=1 ||
        in->dims->data[1]!=3 || in->dims->data[2]!=40 ||
        in->params.zero_point!=-128 || out->params.zero_point!=0) {
        ESP_LOGE(TAG,"INT8_STREAMING_CONTRACT_FAILED");return;
    }
    ESP_LOGI(TAG,"MODEL_INIT_OK ARENA_USED=%u ARENA_RESERVED=%u",
             (unsigned)interpreter.arena_used_bytes(), (unsigned)kArenaBytes);
    ESP_LOGI(TAG,"INTERNAL_RAM_DELTA=%d PSRAM_DELTA=%d",
             (int)(before_int-heap_caps_get_free_size(MALLOC_CAP_INTERNAL)),
             (int)(before_ps-heap_caps_get_free_size(MALLOC_CAP_SPIRAM)));

    int16_t silence[160]={0};
    int rows=0,calls=0,peak=0;
    int64_t total_us=0;
    for(int fidx=0;fidx<320;fidx++) {
        size_t used=0;
        auto row=FrontendProcessSamples(&f,silence,160,&used);
        if (used!=160 || (row.size && row.size!=40)) {
            ESP_LOGE(TAG,"PCM_FRONTEND_FRAME_FAULT");return;
        }
        if (row.size==40) {
            int8_t *dest=in->data.int8+(rows%3)*40;
            for (int i=0;i<40;i++){
                int q=(int(row.values[i])*2550+3328)/6656-128;
                dest[i]=static_cast<int8_t>(std::clamp(q,-128,127));
            }
            ++rows;
            if (rows%3==0) {
                auto start=esp_timer_get_time();
                if (interpreter.Invoke()!=kTfLiteOk) {
                    ESP_LOGE(TAG,"SYNTHETIC_PCM_MODEL_INVOKE_FAIL");return;
                }
                total_us+=esp_timer_get_time()-start;
                ++calls;
                peak=std::max(peak,int(out->data.uint8[0]));
            }
        }
    }
    ESP_LOGI(TAG,"NO_DEVICE_AUDIO 16k_MONO SILENCE_INVOKES=%d PEAK_UINT8=%d AVG_INVOKE_US=%lld",
        calls,peak,(long long)(calls?total_us/calls:0));
    ESP_LOGW(TAG,"STANDALONE ONLY: no real wake/IO, no measured acoustic acceptance");
}
