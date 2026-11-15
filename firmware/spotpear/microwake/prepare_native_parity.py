"""Isolated public 0.4.9 copy -> local-only native inference diagnostic.

No flash or API calls. The fixture exercises INT8 kernels with exactly the same
inputs used on the host. This does not establish live microphone accuracy.
"""
import argparse,hashlib,json,shutil
from pathlib import Path
from prepare_product import change

VERSION='0.4.10-dev-native-parity-1'


def prepare(root,fixture):
    main=root/'main';meta=json.loads((fixture/'fixture.json').read_text())
    if '0.4.9-dev-owner-wake-test-1' not in (root/'CMakeLists.txt').read_text():raise ValueError('Expected isolated0.4.9 copy')
    if not meta.get('synthetic_only') or meta['model_sha256']!='4ffc532e16b3e20b7ce09099338023b5af304a0e31bf537034bb03dd67a4c5f9':
        raise ValueError('Only the pinned PUBLIC model fixture is allowed')
    header=fixture/'gobot_mww_fixture.h'
    if hashlib.sha256(header.read_bytes()).hexdigest()!=meta['header_sha256'] or not 1<=meta['invocations']<=4096:
        raise ValueError('Invalid fixture')
    config=main/'gobot_mww_config.h'
    if '#define GOBOT_WAKE_ROUTE 0' not in config.read_text():raise ValueError('Production route must stay OFF')
    # A failed acoustic trial must not open provider sessions during diagnostics.
    change(config,'#define GOBOT_WAKE_OWNER_TEST 1','#define GOBOT_WAKE_OWNER_TEST 0')
    shutil.copy2(header,main/header.name)
    source=main/'gobot_mww.cc'
    change(source,'#include "gobot_mww.h"','#include "gobot_mww.h"\n#include "gobot_mww_fixture.h"\n#include "freertos/FreeRTOS.h"\n#include "freertos/task.h"')
    change(source,'unsigned parity_hash{};','unsigned parity_hash{};\nstd::atomic<unsigned> native_calls{},native_delta{},native_different{};')
    code='''    // Same fixed public INT8 inputs as host; never reads/stores microphone audio.
    unsigned parity_max=0, parity_different=0, parity_hash=2166136261u;
    constexpr size_t tests=sizeof(gobot_fixture::expected);
    static_assert(sizeof(gobot_fixture::input)==tests*120,"Fixture shape mismatch");
    static_assert(tests<=4096,"Bounded diagnostic");
    for(size_t i=0;i<tests;++i) {
        std::memcpy(input->data.int8,gobot_fixture::input+i*120,120);
        if(runtime.Invoke()!=kTfLiteOk)return false;
        const auto actual=output->data.uint8[0];
        unsigned delta=unsigned(std::abs(int(actual)-int(gobot_fixture::expected[i])));
        parity_max=std::max(parity_max,delta);parity_different+=delta!=0;
        parity_hash=(parity_hash^actual)*16777619u;
        if((i&31)==31)vTaskDelay(pdMS_TO_TICKS(1)); // Do not starve idle/watchdog.
    }
    ESP_LOGI("mww","GOBOT_NATIVE_PARITY calls=%u max_delta=%u different=%u hash=%u host_tolerance=3",
        unsigned(tests),parity_max,parity_different,parity_hash);
    native_calls=tests;native_delta=parity_max;native_different=parity_different;
    if(runtime.Reset()!=kTfLiteOk || vars->ResetAll()!=kTfLiteOk)return false;
    if(parity_max>3)return false; // Report failure, never silently relax tolerance.
'''
    change(source,'    interpreter=&runtime;',code+'    interpreter=&runtime;')
    change(source,'void report() {','void report() {\n    ESP_LOGI("mww","GOBOT_NATIVE_PARITY_STATUS calls=%u max_delta=%u different=%u verified=%d",native_calls.load(),native_delta.load(),native_different.load(),int(native_calls.load()>0 && native_delta.load()<=3 && state.load()==1));')
    for path in (root/'CMakeLists.txt',main/'gobot_build_info.h'):change(path,'0.4.9-dev-owner-wake-test-1',VERSION)
    # Correct the old Live-specific denial on B without changing authorization.
    app=main/'application.cc'
    change(app,'auto reason=gobot::String(root,"reason",24);','auto reason=gobot::String(root,"reason",64);')
    change(app,'limit=reason && !strcmp(reason,"hardware_voice_limit")',
        'limit=reason && (!strcmp(reason,"hardware_voice_limit") || !strcmp(reason,"board_session_limit"))')
    old='notice_=limit?"Лимит Live исчерпан":"Нужен допуск Live";'
    s=app.read_text(encoding='utf-8')
    if old in s:
        change(app,old,'notice_=limit?"Лимит разговора исчерпан":"Разговор недоступен";')
    (root/'native-parity-diagnostic.json').write_text(json.dumps({'version':VERSION,'production_qualified':False,
        'owner_trial_compiled':False,'fixture':meta,'flashed':False,'paid_calls':0},indent=2),encoding='utf-8')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('isolated_copy',type=Path);p.add_argument('public_fixture',type=Path)
    a=p.parse_args();prepare(a.isolated_copy,a.public_fixture)
