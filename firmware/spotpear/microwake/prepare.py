"""Overlay native streaming KWS on the audited 0.2.3 touch source; operate on a copy."""
import argparse
import hashlib
import json
import shutil
from pathlib import Path
from parity import fingerprint

HERE=Path(__file__).resolve().parent
def change(path, before, after):
    data=path.read_text()
    if data.count(before)!=1:
        raise ValueError(f"Expected one touch baseline in {path}: {before[:48]}")
    path.write_text(data.replace(before,after))

def prepare(root, pilot, voice_route=False):
    main=root/"main"
    audio=main/"audio/audio_service.cc"
    app=main/"application.cc"
    cfg=(root/"sdkconfig").read_text()
    for setting in ("CONFIG_USE_AUDIO_DEBUGGER","CONFIG_SEND_WAKE_WORD_DATA"):
        if f"# {setting} is not set" not in cfg:
            raise ValueError(f"Unsafe firmware config: {setting}")
    result=json.loads((pilot/"stream-report.json").read_text())
    blob=(pilot/"gobot.tflite").read_bytes()
    if hashlib.sha256(blob).hexdigest()!=result["sha256"] or result["window"]!=3:
        raise ValueError("Model and evaluation report do not match")
    if voice_route:
        ambient=json.loads((pilot/"ambient.json").read_text())
        if not result["candidate_passed"] or ambient["seconds"]<1800 or ambient["false_events"]:
            raise ValueError("Voice-route candidate failed continuous negative or held-out streaming evaluation")
    rows, probe=fingerprint()
    if rows!=98: raise ValueError("Unexpected frontend stride")
    for name in ("gobot_mww.h","gobot_mww.cc","wake_question_buffer.h"):
        shutil.copyfile(HERE/name,main/name)
    (main/"gobot_mww.tflite").write_bytes(blob)
    # A diagnostic image cannot open a session on a false acoustic activation.
    (main/"gobot_mww_config.h").write_text(f"#define GOBOT_FEATURE_HASH {probe}u\n#define GOBOT_WAKE_CUTOFF {int(result['cutoff'])}\n#define GOBOT_WAKE_ROUTE {int(voice_route)}\n")
    manifest=main/"idf_component.yml"
    deps='  espressif/esp-tflite-micro: "1.3.3~1"\n  esphome/esp-micro-speech-features: "1.2.3"\n'
    if deps not in manifest.read_text():
        change(manifest,"dependencies:\n","dependencies:\n"+deps)
    change(root/"CMakeLists.txt",'0.2.3-dev-touch-auto','0.3.0-dev-mww-probe')
    change(main/"gobot_build_info.h",'0.2.3-dev-touch-auto','0.3.0-dev-mww-probe')
    change(main/"CMakeLists.txt",'set(SOURCES "audio/audio_codec.cc"','set(SOURCES "gobot_mww.cc" "audio/audio_codec.cc"')
    change(main/"CMakeLists.txt",'EMBED_FILES ${LANG_SOUNDS}','EMBED_FILES "gobot_mww.tflite" ${LANG_SOUNDS}')
    header=main/"audio/audio_service.h"
    change(header,'    bool IsAfeWakeWord();','''    void SetLocalScan(bool on);
    void ClearLocalWake();
    bool LocalWakePending() const {return local_hold_.load();}
    bool IsAfeWakeWord();''')
    change(header,'    AudioServiceCallbacks callbacks_;','''    std::atomic<bool> local_hold_{false};
    std::atomic<unsigned> local_generation_{0};
    AudioServiceCallbacks callbacks_;''')
    change(audio,'void AudioService::AudioInputTask() {','''#include "gobot_mww.h"
namespace {constexpr EventBits_t kLocalScan = 1u << 5;}
void AudioService::SetLocalScan(bool on) {
    auto bits=xEventGroupGetBits(event_group_);
    if(on && !(bits & kLocalScan)) xEventGroupSetBits(event_group_, kLocalScan);
    else if(!on && (bits & kLocalScan)) ClearLocalWake();
}
void AudioService::ClearLocalWake() {
    local_generation_.fetch_add(1);
    local_hold_=false;
    xEventGroupClearBits(event_group_, kLocalScan);
    gobot_mww::suspended();
    xEventGroupSetBits(event_group_, AS_EVENT_AUDIO_INPUT_STOP_REQUEST);
}
void AudioService::AudioInputTask() {
    unsigned observed=0;''')
    change(audio,'constexpr EventBits_t kAudioInputActiveBits = AS_EVENT_AUDIO_TESTING_RUNNING |','constexpr EventBits_t kAudioInputActiveBits = kLocalScan | AS_EVENT_AUDIO_TESTING_RUNNING |')
    change(audio,'        if (service_stopped_.load()) {\n            // ADC','''        const auto generation=local_generation_.load();
        if(observed!=generation) {gobot_mww::reset();observed=generation;}
        if (service_stopped_.load()) {
            // ADC''')
    change(audio,'        /* Feed the selected audio engine */','''        if ((bits & AS_EVENT_AUDIO_PROCESSOR_RUNNING) && local_hold_.exchange(false)) {
            xEventGroupClearBits(event_group_, kLocalScan);
            int16_t block[160];size_t n;
            while ((n=gobot_mww::take(block,160)) && local_generation_.load()==generation) {
                audio_engine_->Feed(std::vector<int16_t>(block,block+n));
            }
            gobot_mww::reset();
        }
        if ((bits & kLocalScan) && !(bits & AS_EVENT_AUDIO_PROCESSOR_RUNNING)) {
            std::vector<int16_t> pcm;
            if (codec_->input_channels()!=1 || !ReadAudioData(pcm,16000,160) || pcm.empty()) {
                gobot_mww::miss();vTaskDelay(pdMS_TO_TICKS(10));continue;
            }
            if(local_generation_.load()!=generation) continue;
            if(local_hold_.load()) gobot_mww::retain(pcm.data(),pcm.size());
            else if(gobot_mww::feed(pcm.data(),pcm.size()) && local_generation_.load()==generation) {
                local_hold_=true;
                if(callbacks_.on_wake_word_detected) callbacks_.on_wake_word_detected("ГоБот");
            }
            continue;
        }
        /* Feed the selected audio engine */''')
    change(audio,'"audio_input", 2048 * 3','"audio_input", 2048 * 6')
    change(main/"application.h",'    void GoBotPoll();','    uint64_t wake_resume_ms_=0;\n    void GoBotPoll();')
    change(app,'void Application::HandleWakeWordDetectedEvent() { /* Touch release: KWS is not armed. */ }','''#include "gobot_mww.h"
void Application::HandleWakeWordDetectedEvent() {
    if(!audio_service_.LocalWakePending()) return;
    if(!gobot_muted_ && !gobot_turn_.Active() && audio_service_.IsPlaybackIdle() &&
       gobot::NowMs()>=wake_resume_ms_) {
        if(gobot_mww::qualified()) StartGoBotTurn("wake");
        else {
            notice_="Слышу ГоБот";notice_until_=gobot::NowMs()+1800;RenderGoBot();
        }
    }
    if(!gobot_turn_.Active()) {
        audio_service_.ClearLocalWake();wake_resume_ms_=gobot::NowMs()+1500;
    }
}''')
    change(app,'    peak_level_=0;touch_started_=','    if(strcmp(source,"wake")) audio_service_.ClearLocalWake();\n    peak_level_=0;touch_started_=')
    change(app,'void Application::GoBotFinish(const char* reason) {','''void Application::GoBotFinish(const char* reason) {
    audio_service_.ClearLocalWake();
    wake_resume_ms_=gobot::NowMs()+1500;''')
    change(app,'void Application::GoBotPoll() {','''void Application::GoBotPoll() {
    if(!gobot_turn_.Active()) audio_service_.SetLocalScan(!gobot_muted_ && !local_pause_armed_ &&
        gobot::NowMs()>=wake_resume_ms_ && audio_service_.IsPlaybackIdle());''')
    change(app,'        const auto words=audio_service_.GetWakeWords();','        gobot_mww::report();\n        const auto words=audio_service_.GetWakeWords();')
if __name__ == "__main__":
    p=argparse.ArgumentParser()
    p.add_argument("tree",type=Path)
    p.add_argument("model",type=Path)
    p.add_argument("--voice-route",action="store_true",help="Build a qualified wake-to-Brain candidate after the local probe")
    args=p.parse_args()
    prepare(args.tree,args.model,args.voice_route)
