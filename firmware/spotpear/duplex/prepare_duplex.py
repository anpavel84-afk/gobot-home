"""Apply stereo/AEC diagnostic and continuous session overlay on the verified MWW tree."""
from pathlib import Path
import argparse, shutil
HERE=Path(__file__).resolve().parent
def change(p,a,b):
    s=p.read_text()
    if s.count(a)!=1:raise ValueError(f"Baseline mismatch: {p}: {a[:65]}")
    p.write_text(s.replace(a,b))
def prepare(root):
    m=root/"main";a=m/"application.cc";audio=m/"audio/audio_service.cc";header=m/"audio/audio_service.h"
    shutil.copy(HERE/"gobot_duplex.h",m/"gobot_duplex.h")
    change(root/"CMakeLists.txt","0.3.0-dev-mww-probe","0.4.0-dev-duplex")
    change(m/"gobot_build_info.h","0.3.0-dev-mww-probe","0.4.0-dev-duplex")
    codec=m/"audio/codecs/es8311_audio_codec.cc"
    change(codec,'#include "es8311_audio_codec.h"','#include "es8311_audio_codec.h"\n#include "gobot_duplex.h"')
    change(codec,'input_reference_ = false;','input_reference_ = true;')
    change(codec,'input_channels_ = 1;','input_channels_ = 2;')
    change(codec,'            .channel = 1,','            .channel = 2,')
    change(codec,'            .channel_mask = 0,','            .channel_mask = ESP_CODEC_DEV_MAKE_CHANNEL_MASK(0) | ESP_CODEC_DEV_MAKE_CHANNEL_MASK(1),')
    change(codec,'    es8311_cfg.use_mclk = use_mclk;','    es8311_cfg.use_mclk = use_mclk;\n    es8311_cfg.no_dac_ref = false;')
    change(codec,'        ESP_ERROR_CHECK_WITHOUT_ABORT(esp_codec_dev_read(dev_, (void*)dest, samples * sizeof(int16_t)));',
        '        if(esp_codec_dev_read(dev_, dest, samples*sizeof(int16_t))!=ESP_CODEC_DEV_OK){++duplex_probe::read_errors;return 0;}')
    change(codec,'        ESP_ERROR_CHECK_WITHOUT_ABORT(esp_codec_dev_write(dev_, (void*)data, samples * sizeof(int16_t)));',
        '''        std::vector<int16_t> stereo(samples*2);
        for(int i=0;i<samples;++i) stereo[2*i]=stereo[2*i+1]=data[i];
        if(esp_codec_dev_write(dev_,stereo.data(),stereo.size()*sizeof(int16_t))!=ESP_CODEC_DEV_OK){
            ++duplex_probe::write_errors;return 0;
        }''')
    change(codec,'#include <esp_log.h>','#include <esp_log.h>\n#include <vector>')
    change(audio,'#include "audio_service.h"','#include "audio_service.h"\n#include "gobot_duplex.h"')
    change(audio,'    return true;\n}\n\nvoid AudioService::SetLocalScan', '    return true;\n}\n\nvoid AudioService::SetLocalScan') if False else None
    # Inspect before the classifier and before AFE, never archive PCM.
    change(audio,'    /* Update the last input time */','    if(codec_->input_channels()==2) duplex_probe::raw(data.data(),data.size());\n    /* Update the last input time */')
    change(audio,'            if (codec_->input_channels()!=1 || !ReadAudioData(pcm,16000,160) || pcm.empty()) {',
      '            if (!ReadAudioData(pcm,16000,160) || pcm.empty()) {')
    change(audio,'            if(local_generation_.load()!=generation) continue;\n            if(local_hold_.load())',
      '''            if(codec_->input_channels()==2){
                for(size_t i=0;i<pcm.size()/2;++i)pcm[i]=pcm[2*i];
                pcm.resize(pcm.size()/2);
            }
            if(local_generation_.load()!=generation) continue;
            if(local_hold_.load())''')
    # Wake tail must enter the same interleaved AFE format with a quiet reference.
    change(audio,'                audio_engine_->Feed(std::vector<int16_t>(block,block+n));',
      '''                std::vector<int16_t> input(n*codec_->input_channels(),0);
                for(size_t k=0;k<n;++k)input[k*codec_->input_channels()]=block[k];
                audio_engine_->Feed(std::move(input));''')
    change(audio,'        PushTaskToEncodeQueue(kAudioTaskTypeEncodeToSendQueue, std::move(data));',
      '''        duplex_probe::processed(data.data(),data.size(),voice_detected_);
        PushTaskToEncodeQueue(kAudioTaskTypeEncodeToSendQueue, std::move(data));''')
    change(header,'    void EnableDeviceAec(bool enable);','    void EnableDeviceAec(bool enable);\n    void DiagnosticAudio(unsigned sample_offset);')
    audio.write_text(audio.read_text()+'''
void AudioService::DiagnosticAudio(unsigned offset) {
    std::lock_guard<std::mutex> lock(audio_queue_mutex_);
    if(audio_playback_queue_.size()>=MAX_PLAYBACK_TASKS_IN_QUEUE)return;
    AudioTask task{};task.type=kAudioTaskTypeDecodeToPlaybackQueue;
    task.pcm.resize(2400);
    for(unsigned i=0;i<2400;++i){
        const double t=double(i+offset)/24000;
        task.pcm[i]=int16_t(1800*(sin(2*3.14159265*437*t)+.5*sin(2*3.14159265*883*t)));
    }
    playback_drained_notified_=false;audio_playback_queue_.push_back(std::move(task));audio_queue_cv_.notify_all();
}
''')
    change(m/"application.h",'    uint64_t wake_resume_ms_=0;',
      '    bool duplex_armed_=false;uint64_t duplex_started_=0;unsigned duplex_samples_=0;\n    uint64_t wake_resume_ms_=0;')
    change(a,'#include "application.h"','#include "application.h"\n#include "gobot_duplex.h"')
    change(a,'    peak_level_=0;touch_started_=gobot::NowMs();','''    peak_level_=0;touch_started_=gobot::NowMs();
    if(duplex_armed_){
        duplex_armed_=false;
        if(!gobot_turn_.Begin(touch_started_))return;
        gobot_turn_.Connected(touch_started_);local_pause_active_=true;
        duplex_started_=touch_started_;duplex_samples_=0;duplex_probe::start();
        audio_service_.EnableVoiceProcessing(true);audio_service_.EnableDeviceAec(true);
        notice_="Проверка дуплекса";RenderGoBot();return;
    }''')
    change(a,'void Application::GoBotPoll() {','''void Application::GoBotPoll() {
    if(duplex_started_){
        const auto elapsed=gobot::NowMs()-duplex_started_;
        while(audio_service_.PopPacketFromSendQueue()){}
        if(elapsed<8000){audio_service_.DiagnosticAudio(duplex_samples_);duplex_samples_+=2400;}
        if(elapsed>=11000){duplex_probe::report();duplex_started_=0;GoBotFinish("duplex_check_complete");}
        RenderGoBot();return;
    }''')
    change(a,'    reported_playing_=false;local_pause_active_=false;','    reported_playing_=false;local_pause_active_=false;duplex_started_=0;')
    change(a,'    if(page.view==View::Ready && local_pause_armed_) {','''    if(duplex_started_ || (page.view==View::Ready && duplex_armed_)) {
        page.view=View::Notice;page.value=duplex_started_?"Говорите поверх звука":"Проверка дуплекса";
        page.detail=duplex_started_?"Локальная проверка":"Коснитесь для теста";
    } else if(page.view==View::Ready && local_pause_armed_) {''')
    change(a,'    } else if(line=="GOBOT_STATUS") {','''    } else if(line=="GOBOT_DUPLEX_BEGIN" && !gobot_turn_.Active() && !gobot_muted_) {\n        duplex_armed_=true;StartGoBotTurn("diagnostic");\n    } else if(line=="GOBOT_DUPLEX_CHECK" && !gobot_turn_.Active() && !gobot_muted_) {
        duplex_armed_=true;RenderGoBot();ESP_LOGI(TAG,"GOBOT_DUPLEX_ARMED local=1");
    } else if(line=="GOBOT_STATUS") {
        duplex_probe::report();''')
    change(a,'if(!gobot_turn_.Active()) audio_service_.SetLocalScan(!gobot_muted_ && !local_pause_armed_ &&',
      'if(!gobot_turn_.Active()) audio_service_.SetLocalScan(!gobot_muted_ && !duplex_armed_ && !local_pause_armed_ &&')
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("tree",type=Path);args=p.parse_args();prepare(args.tree)
