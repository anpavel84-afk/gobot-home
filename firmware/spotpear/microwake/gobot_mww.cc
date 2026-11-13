#include "gobot_mww.h"
#include "gobot_mww_config.h"
#include "wake_question_buffer.h"
#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstring>
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "frontend.h"
#include "frontend_util.h"
#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/micro/micro_mutable_op_resolver.h"
#include "tensorflow/lite/micro/micro_resource_variable.h"

extern const unsigned char model_bytes[] asm("_binary_gobot_mww_tflite_start");
namespace gobot_mww {
namespace {
FrontendState front{};
tflite::MicroInterpreter* interpreter = nullptr;
tflite::MicroResourceVariables* vars = nullptr;
std::atomic<int> state{0};
std::atomic<unsigned> frames{}, invocations{}, peak{}, max_us{}, hits{}, misses{}, clips{}, levels{}, drops{}, pauses{}, errors{};
unsigned step{}, position{}, history[3]{}, warm{};
constexpr size_t capacity = 192000; // 12 seconds incl. 1s local prefix, 16kHz mono.
int16_t* tail = nullptr;
gobot::WakeQuestionBuffer question;
std::atomic<bool> overflow{};
unsigned parity_hash{};
bool initialize() {
    FrontendConfig c{};
    FrontendFillConfigWithDefaults(&c);
    c.window.size_ms=30; c.window.step_size_ms=10;
    c.filterbank.num_channels=40; c.filterbank.lower_band_limit=125; c.filterbank.upper_band_limit=7500;
    c.noise_reduction.smoothing_bits=10; c.noise_reduction.even_smoothing=.025;
    c.noise_reduction.odd_smoothing=.06; c.noise_reduction.min_signal_remaining=.05;
    c.pcan_gain_control.enable_pcan=true; c.pcan_gain_control.strength=.95;
    c.pcan_gain_control.offset=80; c.pcan_gain_control.gain_bits=21;
    c.log_scale.enable_log=true; c.log_scale.scale_shift=6;
    if (!FrontendPopulateState(&c,&front,16000)) return false;
    uint32_t lcg=17, hash=2166136261u, rows=0;
    int16_t block[160];
    for(int f=0;f<100;++f) {
        for(auto& sample:block) {lcg=1664525u*lcg+1013904223u;sample=int(lcg>>19)-4096;}
        size_t used=0;
        auto result=FrontendProcessSamples(&front,block,160,&used);
        if(used!=160 || (result.size && result.size!=40)) return false;
        if(result.size) ++rows;
        for(size_t k=0;k<result.size;++k) hash=(hash^result.values[k])*16777619u;
    }
    parity_hash=hash;
    ESP_LOGI("mww","GOBOT_PARITY rows=%u hash=%u",unsigned(rows),unsigned(hash));
    if(rows!=98 || hash!=GOBOT_FEATURE_HASH) return false;
    FrontendReset(&front);
    static tflite::MicroMutableOpResolver<13> ops;
    if(ops.AddCallOnce()!=kTfLiteOk || ops.AddVarHandle()!=kTfLiteOk ||
       ops.AddReshape()!=kTfLiteOk || ops.AddReadVariable()!=kTfLiteOk ||
       ops.AddStridedSlice()!=kTfLiteOk || ops.AddConcatenation()!=kTfLiteOk ||
       ops.AddAssignVariable()!=kTfLiteOk || ops.AddConv2D()!=kTfLiteOk ||
       ops.AddFullyConnected()!=kTfLiteOk || ops.AddLogistic()!=kTfLiteOk ||
       ops.AddQuantize()!=kTfLiteOk || ops.AddDepthwiseConv2D()!=kTfLiteOk ||
       ops.AddAveragePool2D()!=kTfLiteOk) return false;
    const tflite::Model* model=tflite::GetModel(model_bytes);
    if(model->version()!=TFLITE_SCHEMA_VERSION) return false;
    constexpr size_t arena_size=128*1024;
    constexpr uint32_t caps=MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT;
    auto arena=static_cast<uint8_t*>(heap_caps_aligned_alloc(16,arena_size,caps));
    auto var_memory=static_cast<uint8_t*>(heap_caps_aligned_alloc(16,2048,caps));
    tail=static_cast<int16_t*>(heap_caps_calloc(capacity,sizeof(int16_t),caps));
    if(!arena || !var_memory || !tail) return false;
    question.Attach(tail,capacity,16000);
    auto allocator=tflite::MicroAllocator::Create(var_memory,2048);
    if(!allocator) return false;
    vars=tflite::MicroResourceVariables::Create(allocator,20);
    if(!vars) return false;
    static tflite::MicroInterpreter runtime(model,ops,arena,arena_size,vars);
    if(runtime.AllocateTensors()!=kTfLiteOk) return false;
    auto input=runtime.input(0); auto output=runtime.output(0);
    if(input->type!=kTfLiteInt8 || input->dims->size!=3 || input->dims->data[0]!=1 ||
       input->dims->data[1]!=3 || input->dims->data[2]!=40 || output->type!=kTfLiteUInt8 ||
       output->bytes!=1 || input->params.zero_point!=-128 ||
       std::abs(input->params.scale-26.f/255.f)>.00001f) return false;
    interpreter=&runtime;
    ESP_LOGI("mww","GOBOT_MWW_MEMORY used=%u arena=%u heap=%u psram=%u",unsigned(runtime.arena_used_bytes()),
             unsigned(arena_size),unsigned(heap_caps_get_free_size(MALLOC_CAP_INTERNAL)),
             unsigned(heap_caps_get_free_size(MALLOC_CAP_SPIRAM)));
    return true;
}
}
void reset() {
    if(interpreter) {
        FrontendReset(&front);
        if(interpreter->Reset()!=kTfLiteOk || vars->ResetAll()!=kTfLiteOk) state=-1;
    }
    question.Clear();
    step=position=warm=0;
    std::fill(std::begin(history),std::end(history),0u);
}
bool feed(const int16_t* mono,size_t count) {
    if(state==0) state=initialize()?1:-1;
    if(state!=1) return false;
    question.Observe(mono,count); // Local RAM only; no transport in standby.
    unsigned level=0;
    for(size_t i=0;i<count;++i) {
        auto sample=unsigned(std::abs(int(mono[i])));
        level=std::max(level,sample);
        if(sample>=32760) ++clips;
    }
    levels=level;
    auto start=esp_timer_get_time();
    bool detected=false;
    while(count) {
        size_t used=0;
        auto row=FrontendProcessSamples(&front,mono,count,&used);
        if(!used || used>count) {++errors;break;}
        count-=used; mono+=used;
        if(!row.size) continue;
        if(row.size!=40) {state=-1;++errors;break;}
        auto slot=interpreter->input(0)->data.int8+step*40;
        for(int i=0;i<40;++i) {
            const int q=(int(row.values[i])*2550+3328)/6656-128;
            slot[i]=std::clamp(q,-128,127);
        }
        ++frames;
        if(++step<3) continue;
        step=0;
        if(interpreter->Invoke()!=kTfLiteOk) {state=-1;++errors;break;}
        auto prob=interpreter->output(0)->data.uint8[0];
        peak=std::max(peak.load(),unsigned(prob));
        history[position++%3]=prob;
        ++invocations;
        if(++warm>=25 && history[0]+history[1]+history[2]>=3*GOBOT_WAKE_CUTOFF) {
            ++hits;detected=true;break;
        }
    }
    max_us=std::max(max_us.load(),unsigned(esp_timer_get_time()-start));
    return detected && question.Activate();
}
void retain(const int16_t* pcm,size_t count) {
    if(!question.Append(pcm,count)) {++drops;overflow=true;}
}
size_t take(int16_t* pcm,size_t limit) {
    return question.Take(pcm,limit);
}
bool consume_overflow(){return overflow.exchange(false);}
void report() {
    ESP_LOGI("mww","GOBOT_MWW state=%d frames=%u invokes=%u peak=%u hits=%u max_us=%u level=%u clipped=%u underrun=%u tail_drop=%u suspend=%u errors=%u parity=%u routed=%d",
             state.load(),frames.load(),invocations.load(),peak.load(),hits.load(),max_us.load(),levels.load(),
             clips.load(),misses.load(),drops.load(),pauses.load(),errors.load(),parity_hash,int(GOBOT_WAKE_ROUTE));
}
void miss(){++misses;}
void suspended(){++pauses;}
bool qualified(){return GOBOT_WAKE_ROUTE;}
}
