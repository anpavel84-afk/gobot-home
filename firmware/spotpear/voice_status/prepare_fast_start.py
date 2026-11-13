"""Apply only to a COPY of installed 0.4.4-dev-voice-status-1. No flash."""
from pathlib import Path
import argparse

def change(path,old,new):
    text=path.read_text()
    if text.count(old)!=1:raise ValueError(f'Baseline mismatch: {path.name}: {old[:70]}')
    path.write_text(text.replace(old,new))

def prepare(root):
    m=root/'main';app=m/'application.cc';audio=m/'audio/audio_service.cc';header=m/'audio/audio_service.h'
    change(header,'#define MAX_SEND_PACKETS_IN_QUEUE (2400 / OPUS_FRAME_DURATION_MS)',
           '#define MAX_SEND_PACKETS_IN_QUEUE (7200 / OPUS_FRAME_DURATION_MS)')
    change(header,'    void EnableVoiceProcessing(bool enable);', '''    void EnableVoiceProcessing(bool enable);
    void HoldStartupAudio(bool enabled) {startup_audio_hold_.store(enabled);if(enabled)startup_audio_overflow_.store(false);}
    bool StartupAudioOverflow() const {return startup_audio_overflow_.load();}''')
    change(header,'    FixedQueue<std::unique_ptr<AudioStreamPacket>, MAX_SEND_PACKETS_IN_QUEUE> audio_send_queue_;',
        '''    std::atomic<bool> startup_audio_hold_{false},startup_audio_overflow_{false};
    FixedQueue<std::unique_ptr<AudioStreamPacket>, MAX_SEND_PACKETS_IN_QUEUE> audio_send_queue_;''')
    change(audio,'audio_input_need_warmup_ = true;',
        'audio_input_need_warmup_ = !startup_audio_hold_.load(); // Local startup keeps the first syllable.')
    change(audio,'''                            if (audio_send_queue_.size() >= MAX_SEND_PACKETS_IN_QUEUE) {
                                audio_send_queue_.pop_front();
                            }
                            audio_send_queue_.push_back(std::move(packet));''', '''                            const bool startup=startup_audio_hold_.load();
                            const size_t limit=startup?MAX_SEND_PACKETS_IN_QUEUE:(2400 / OPUS_FRAME_DURATION_MS);
                            if(startup && (startup_audio_overflow_.load() || audio_send_queue_.size()>=limit)) {
                                startup_audio_overflow_.store(true);
                            } else {
                                if(audio_send_queue_.size()>=limit)audio_send_queue_.pop_front();
                                audio_send_queue_.push_back(std::move(packet));
                            }''')
    change(m/'application.h','bool gobot_access_received_=false,', 'bool gobot_early_capture_=false;\n    bool gobot_access_received_=false,')
    change(app,'        if (bits & MAIN_EVENT_SEND_AUDIO) {',
        '        if ((bits & MAIN_EVENT_SEND_AUDIO) && !gobot_early_capture_) {')
    change(app,'    ++activation_count_;\n    notice_until_=0; weather_until_=0;', '''    ++activation_count_;
    // Explicit touch starts local capture before TLS/provider setup. No uplink
    // until the existing access and media-ready checks authorize transmission.
    while(auto packet=audio_service_.PopPacketFromSendQueue())std::fill(packet->payload.begin(),packet->payload.end(),0);
    gobot_early_capture_=true;audio_service_.HoldStartupAudio(true);
    Board::GetInstance().SetPowerSaveLevel(PowerSaveLevel::PERFORMANCE);
    audio_service_.EnableVoiceProcessing(true);audio_service_.EnableDeviceAec(true);
    if(!audio_service_.IsAudioProcessorRunning()){GoBotFinish("capture_failed");return;}
    ESP_LOGI(TAG,"GOBOT_LOCAL_CAPTURE started_ms=%u",unsigned(gobot::NowMs()-touch_started_));
    notice_until_=0; weather_until_=0;''')
    change(app,'    case gobot::Phase::Connecting:page.view=View::Connecting;break;',
        '    case gobot::Phase::Connecting:page.view=gobot_early_capture_?View::Listening:View::Connecting;break;')
    change(app,'    case gobot::Phase::Capturing:page.view=(!gobot_access_received_ || (live_continuous_ && !gobot_media_ready_))?View::Connecting:View::Listening;break;',
        '    case gobot::Phase::Capturing:page.view=gobot_early_capture_?View::Listening:(!gobot_access_received_ || (live_continuous_ && !gobot_media_ready_))?View::Connecting:View::Listening;break;')
    change(app,'else if(gobot_ui_phase_=="connecting") page.view=View::Connecting;',
        'else if(gobot_ui_phase_=="connecting" && !gobot_early_capture_) page.view=View::Connecting;')
    change(app,'if (play_popup_on_listening_ || !audio_service_.IsAudioProcessorRunning()) {',
        'if (play_popup_on_listening_ || !audio_service_.IsAudioProcessorRunning() || gobot_early_capture_) {')
    change(app,'''    if(!gobot_access_received_ || (live_continuous_ && !gobot_media_ready_)) return;
    audio_service_.EnableVoiceProcessing(true);''', '''    if(!gobot_access_received_ || (live_continuous_ && !gobot_media_ready_)) return;
    if(gobot_early_capture_) {
        if(audio_service_.StartupAudioOverflow()){GoBotFinish("startup_buffer_overflow");return;}
        gobot_early_capture_=false;audio_service_.HoldStartupAudio(false);
        xEventGroupSetBits(event_group_,MAIN_EVENT_SEND_AUDIO);
    }
    if(!audio_service_.IsAudioProcessorRunning())audio_service_.EnableVoiceProcessing(true);''')
    change(app,'void Application::GoBotFinish(const char* reason) {', '''void Application::GoBotFinish(const char* reason) {
    gobot_early_capture_=false;audio_service_.HoldStartupAudio(false);''')
    change(app,'    while(audio_service_.PopPacketFromSendQueue()) {}',
        '    while(auto packet=audio_service_.PopPacketFromSendQueue())std::fill(packet->payload.begin(),packet->payload.end(),0);')
    change(app,'void Application::GoBotPoll() {', '''void Application::GoBotPoll() {
    if(gobot_early_capture_ && audio_service_.StartupAudioOverflow()) {
        GoBotFinish("startup_buffer_overflow");notice_="Связь задержалась";notice_until_=gobot::NowMs()+4500;RenderGoBot();return;
    }''')
    for p in (root/'CMakeLists.txt',m/'gobot_build_info.h'):
        change(p,'0.4.4-dev-voice-status-1','0.4.5-dev-fast-start-1')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('copy_of_voice_status',type=Path);prepare(p.parse_args().copy_of_voice_status)
