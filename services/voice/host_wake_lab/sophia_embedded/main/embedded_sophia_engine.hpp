#pragma once
// HOST-B ESP_LOCAL only; proof of usable 16-kHz PCM API, NOT installed RC1.
// This DOES NOT read I2S/ES8311, control Wi-Fi/Opus/Brain, or flash anything.
// HOST-A must call ingest_existing_pcm() only from its bounded worker.
#include <cstddef>
#include <cstdint>
#include <cstring>
#include "esp_log.h"
#include "esp_timer.h"
#include "model_path.h"
#include "esp_wn_iface.h"
#include "esp_wn_models.h"
#include "sophia_pcm_tap.hpp"

extern const unsigned char sophia_embedded_start[] asm("_binary_sophia_srmodels_bin_start");
extern const unsigned char sophia_embedded_end[] asm("_binary_sophia_srmodels_bin_end");

namespace gobot_sophia {
class EmbeddedSophiaEngine {
public:
    using Notify = void(*)(const WakeEvidence& evidence, void *context);
    EmbeddedSophiaEngine()=default;
    EmbeddedSophiaEngine(const EmbeddedSophiaEngine&)=delete;
    EmbeddedSophiaEngine& operator=(const EmbeddedSophiaEngine&)=delete;

    bool initialize() {
        if(models_ || model_)return false;
        // Single, exact, offline-verified official packed model. No model partition.
        auto sz=static_cast<size_t>(sophia_embedded_end-sophia_embedded_start);
        static const uint8_t count_one[4]={1,0,0,0};
        if(sz!=383508 || std::memcmp(sophia_embedded_start,count_one,4)!=0 ||
           std::memcmp(sophia_embedded_start+4,"wn10_sophia",11)!=0) {
            ESP_LOGE("SOPHIA_B", "EMBEDDED_SOPHIA_MODEL_HEADER_INVALID bytes=%u",
                     unsigned(sz));
            return false;
        }
        models_=srmodel_load(sophia_embedded_start);
        if(!models_ || models_->num!=1){
            ESP_LOGE("SOPHIA_B","SOPHIA_MODEL_LIST_LOAD_FAILED");
            close();
            return false;
        }
        char *chosen=esp_srmodel_filter(models_,ESP_WN_PREFIX,nullptr);
        if(!chosen || std::strcmp(chosen,"wn10_sophia")!=0) {
            ESP_LOGE("SOPHIA_B","SOPHIA_ONLY_EXACT_MODEL_REQUIRED");
            close();
            return false;
        }
        iface_=esp_wn_handle_from_name(chosen);
        if(!iface_) { close(); return false; }
        int64_t started=esp_timer_get_time();
        model_=iface_->create(chosen,DET_MODE_90);
        init_time_us_=static_cast<uint64_t>(esp_timer_get_time()-started);
        if(!model_) { close(); return false; }
        const int rate=iface_->get_samp_rate(model_);
        const int channels=iface_->get_channel_num(model_);
        const int model_chunk=iface_->get_samp_chunksize(model_);
        if(rate!=16000 || channels!=1 || model_chunk<=0 ||
           model_chunk>static_cast<int>(ContiguousMonoPcmTap::kNativeChunkMax)){
            ESP_LOGE("SOPHIA_B","PCM_CONTRACT_MISMATCH rate=%d mic=%d chunk=%d",
                     rate,channels,model_chunk);
            close();return false;
        }
        tap_=ContiguousMonoPcmTap(static_cast<size_t>(model_chunk));
        ESP_LOGI("SOPHIA_B","EMBEDDED_SOPHIA_LOADED no_model_partition=1 native_chunk=%d init_us=%llu",
                 model_chunk,static_cast<unsigned long long>(init_time_us_));
        return true;
    }

    bool set_owner(WakeOwner next) {
        const bool okay=gate_.switch_to(next);
        if(okay) tap_.reset(); // never reuse old PCM across a wake-owner switch
        return okay;
    }
    void set_phase(DevicePhase next) {
        gate_.set_phase(next);
        if(next!=DevicePhase::IDLE)tap_.reset();
    }
    void set_turn_pending(bool pending) {gate_.set_pending(pending);}
    void new_stream_epoch() {tap_.reset();gate_.begin_new_audio_epoch();}
    bool allow_plan_stream_wake() const {return gate_.allow_plan_wake();}
    bool installed_sophia_model_ready() const {return model_!=nullptr;}

    // HOST-A glue reference:
    // Called on A's existing audio worker AFTER bounded queue transfer,
    // never in the I2S ISR. The input is mono 16k signed PCM in UNITS of
    // samples, with the same epoch/sample index sent through Opus.
    // Real device transport must be added/approved by A, not B.
    bool ingest_existing_pcm(uint32_t epoch,uint64_t start_sample,
                             const int16_t *pcm,size_t samples,
                             uint64_t packet_receive_us,
                             Notify on_wake=nullptr,void *context=nullptr) {
        if(!model_ || !gate_.eligible_for_local_wake())return false;
        const uint32_t generation=gate_.generation();
        const bool continuous=tap_.feed(epoch,start_sample,pcm,samples,
          [&](const int16_t* one,size_t /*count*/,uint64_t end_sample) {
            auto started=static_cast<uint64_t>(esp_timer_get_time());
            const int detection=iface_->detect(model_,const_cast<int16_t*>(one));
            const uint64_t finished=static_cast<uint64_t>(esp_timer_get_time());
            total_infer_us_+=finished-started;
            ++native_frames_;
            if(detection==WAKENET_DETECTED) {
                ++raw_detections_;
                if(gate_.accept_local_wake(generation,end_sample)) {
                    ++accepted_wakes_;
                    WakeEvidence evidence{end_sample,packet_receive_us,finished,
                        finished-started,epoch,generation};
                    if(on_wake)on_wake(evidence,context);
                }else{
                    ++suppressed_duplicates_;
                }
            }
        });
        if(!continuous)++sequence_failures_;
        return continuous;
    }

    unsigned raw_detections()const{return raw_detections_;}
    unsigned accepted_wakes()const{return accepted_wakes_;}
    uint64_t inference_frames()const{return native_frames_;}
    uint64_t total_infer_us()const{return total_infer_us_;}
    uint64_t init_time_us()const{return init_time_us_;}
    unsigned dropped_sequences()const{return sequence_failures_;}
    unsigned duplicate_suppressions()const{return suppressed_duplicates_;}

    void close() {
        if(model_ && iface_)iface_->destroy(model_);
        model_=nullptr;iface_=nullptr;
        if(models_)esp_srmodel_deinit(models_);
        models_=nullptr;
        tap_.reset();
    }
private:
    srmodel_list_t *models_=nullptr;
    const esp_wn_iface_t *iface_=nullptr;
    model_iface_data_t *model_=nullptr;
    ExclusiveWakeGate gate_{};
    ContiguousMonoPcmTap tap_{512};
    uint64_t init_time_us_{0},total_infer_us_{0},native_frames_{0};
    unsigned raw_detections_{0},accepted_wakes_{0};
    unsigned sequence_failures_{0},suppressed_duplicates_{0};
};
} // namespace gobot_sophia