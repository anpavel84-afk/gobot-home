#include "gobot_raw_wake.h"
#include "raw_wake_capture.h"
#include "guided_wake_prompts.h"
#include <esp_heap_caps.h>
#include <esp_timer.h>
#include <driver/usb_serial_jtag.h>
#include <driver/usb_serial_jtag_vfs.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <mbedtls/base64.h>
#include <cstdio>
#include <cstdlib>
#include <algorithm>

namespace gobot_raw_wake {
static raw_wake::Capture* capture=nullptr;
static std::atomic<bool> initialized{false};
static std::string nonce;
static std::atomic<bool> exporting{false},cancelled{false};
static bool guided=false;
static uint64_t clock_ms(){return esp_timer_get_time()/1000;}
static uint32_t crc(const uint8_t* p,size_t n){
    uint32_t v=~0u;while(n--){v^=*p++;for(int i=0;i<8;++i)v=(v>>1)^(0xedb88320u&-(v&1));}return ~v;
}
bool busy(){return exporting || (initialized.load() && capture->state()!=raw_wake::State::Empty);}
static void erase(){if(capture)heap_caps_free(capture->release_storage());}
// Raw payloads bypass ESP logging. The dedicated, explicit USB collector must
// validate every chunk; a disconnected/slow host cannot retain board RAM forever.
static bool write_line(const char* data,size_t size,uint64_t deadline){
    size_t offset=0;
    flockfile(stdout); // Do not interleave PCM framing with console log lines.
    while(offset<size && !cancelled && clock_ms()<deadline){
        int n=usb_serial_jtag_write_bytes(data+offset,size-offset,pdMS_TO_TICKS(20));
        if(n>0)offset+=n;else vTaskDelay(pdMS_TO_TICKS(1));
    }
    funlockfile(stdout);return offset==size;
}
static void export_task(void*){
    const uint64_t deadline=clock_ms()+20000;
    const auto* bytes=reinterpret_cast<const uint8_t*>(capture->data());
    const size_t size=capture->size()*2;char line[1550];unsigned seq=0;bool ok=bytes;
    int n=snprintf(line,sizeof(line),"\nGOBOT_RAW_BEGIN %s %u 16000 mono_pcm16_pre_afe\n",nonce.c_str(),unsigned(size));
    ok=ok && write_line(line,n,deadline);
    for(size_t offset=0;ok && offset<size;offset+=960){
        const size_t count=std::min(size_t(960),size-offset);unsigned char encoded[1281];size_t len=0;
        ok=mbedtls_base64_encode(encoded,sizeof(encoded),&len,bytes+offset,count)==0;
        if(!ok)break;
        n=snprintf(line,sizeof(line),"\nGOBOT_RAW_DATA %s %u %08lx %.*s\n",nonce.c_str(),seq++,
            static_cast<unsigned long>(crc(bytes+offset,count)),int(len),encoded);
        ok=write_line(line,n,deadline);
    }
    if(ok){n=snprintf(line,sizeof(line),"\nGOBOT_RAW_END %s %u %08lx\n",nonce.c_str(),seq,
        static_cast<unsigned long>(crc(bytes,size)));write_line(line,n,deadline);}
    erase();exporting=false;vTaskDelete(nullptr);
}
static bool prepare_usb(){
    if(usb_serial_jtag_is_driver_installed())return true;
    usb_serial_jtag_driver_config_t config{.tx_buffer_size=8192,.rx_buffer_size=1024};
    if(usb_serial_jtag_driver_install(&config)!=ESP_OK)return false;
    usb_serial_jtag_vfs_use_driver();return true;
}
bool command(const std::string& line,bool idle,bool muted,uint64_t now){
    if(line=="GOBOT_RAW_USB_PREPARE"){
        if(idle && !busy() && prepare_usb()){printf("GOBOT_RAW_USB_READY\n");fflush(stdout);}return true;
    }
    if(line=="GOBOT_RAW_STATUS"){
        printf("GOBOT_RAW_STATUS capable_guided=1 state=%d guided=%d samples=%u\n",capture?int(capture->state()):0,int(guided),capture?unsigned(capture->recorded_samples()):0);fflush(stdout);return true;
    }
    if(line=="GOBOT_RAW_CANCEL"){
        cancelled=true;if(capture && !exporting)erase();guided=false;return true;
    }
    const bool wants_guided=line.rfind("GOBOT_RAW_GUIDED_ARM ",0)==0;
    if(!wants_guided && line.rfind("GOBOT_RAW_ARM ",0)!=0)return false;
    // Format: GOBOT_RAW_ARM <32 lowercase hex nonce> <15..60 seconds>.
    const auto arg=line.substr(wants_guided?21:14);const auto space=arg.find(' ');
    if(space!=32 || arg.substr(0,32).find_first_not_of("0123456789abcdef")!=std::string::npos)return true;
    const auto duration=arg.substr(space+1);
    if(duration.empty() || duration.size()>2 || duration.find_first_not_of("0123456789")!=std::string::npos)return true;
    const int seconds=atoi(duration.c_str());
    if(!idle || muted || busy() || seconds<15 || seconds>60 || (wants_guided && seconds!=50))return true;
    if(!prepare_usb())return true;
    if(!capture){
        capture=new raw_wake::Capture(nullptr,0);initialized.store(true);
    }
    auto* buffer=static_cast<int16_t*>(heap_caps_calloc(60*16000,sizeof(int16_t),MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
    if(!buffer)return true;
    if(!capture->attach(buffer,60*16000)){heap_caps_free(buffer);return true;}
    nonce=arg.substr(0,32);cancelled=false;guided=wants_guided;
    if(capture->arm(seconds,now)){printf("%s %s %d\n",guided?"GOBOT_RAW_GUIDED_ARMED":"GOBOT_RAW_ARMED",nonce.c_str(),seconds);fflush(stdout);}
    return true;
}
bool touch(bool physical,bool hold,uint64_t now){
    if(!busy())return false;
    if(hold){cancelled=true;if(!exporting)erase();}
    else if(capture && capture->start(physical,now))printf("GOBOT_RAW_STARTED %s\n",nonce.c_str());
    return true;
}
void feed(const int16_t* pcm,size_t n){if(initialized.load())capture->feed(pcm,n);}
void missed_block(){if(initialized.load())capture->missed_block();}
void poll(uint64_t now){
    if(!capture || exporting)return;
    if(capture->poll(now)){erase();return;}
    if(capture->state()==raw_wake::State::Failed){erase();printf("GOBOT_RAW_FAILED\n");return;}
    if(capture->state()==raw_wake::State::Ready){
        exporting=true;
        if(xTaskCreate(export_task,"raw_usb",6144,nullptr,1,nullptr)!=pdPASS){erase();exporting=false;}
    }
}
const char* label(){
    if(exporting)return "Передача по USB";
    if(capture && capture->state()==raw_wake::State::Recording)return guided?guided_wake::at(capture->recorded_samples()).text:"Локальная запись";
    return guided?"Коснитесь один раз":"Коснитесь для записи";
}
const char* detail(){
    if(exporting)return "Запись завершена";
    if(guided && capture && capture->state()==raw_wake::State::Recording)return guided_wake::at(capture->recorded_samples()).hint;
    return guided?"Настройка ГоБот":"Без облака";
}
}
