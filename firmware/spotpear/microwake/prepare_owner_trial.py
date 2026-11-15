"""COPY of public0.4.8 -> unarmed bounded Owner trial; no weights/flash/API."""
import argparse,hashlib,json,shutil
from pathlib import Path
from prepare_product import change
from prepare_private_template import configure_reference_runtime
HERE=Path(__file__).resolve().parent
VERSION='0.4.9-dev-owner-wake-test-1'


def prepare(root):
    main=root/'main'
    if '0.4.8-dev-reference-local-1' not in (root/'CMakeLists.txt').read_text(encoding='utf-8'):raise ValueError('Expected isolated reference0.4.8 source copy')
    config=main/'gobot_mww_config.h'
    if '#define GOBOT_WAKE_ROUTE 0' not in config.read_text() or 'GOBOT_WAKE_OWNER_TEST' in config.read_text():raise ValueError('Production route must stay OFF; trial must be new')
    blob=(main/'gobot_mww.tflite').read_bytes()
    if hashlib.sha256(blob).hexdigest()!='1e26ad59e1a9a5773b0310fc03d5b689dfa575b7f1521aa63e9299239b27e2e4':raise ValueError('Only a public placeholder belongs on the build host')
    for name in ('gobot_mww.cc','gobot_mww.h','wake_question_buffer.h','probability_window.h','wake_trial_window.h'):shutil.copy2(HERE/name,main/name)
    configure_reference_runtime(main/'gobot_mww.cc')
    with config.open('a') as output:output.write('\n#define GOBOT_WAKE_OWNER_TEST 1\n#define GOBOT_WAKE_PREFIX_SAMPLES 32000\n')
    app=main/'application.cc'
    change(app,'if(gobot_mww::qualified()) StartGoBotTurn("wake");','if(gobot_mww::qualified() || gobot_mww::claim_owner_test()) StartGoBotTurn("wake");')
    old='if(page.view==View::Ready && !gobot_muted_ && gobot_mww::qualified() && gobot_mww::ready() && audio_service_.IsLocalScanRunning())page.detail="Скажите ГоБот";'
    new='if(page.view==View::Ready && !gobot_muted_ && gobot_mww::ready() && audio_service_.IsLocalScanRunning()) {\n        if(gobot_mww::qualified())page.detail="Скажите ГоБот";\n        else if(gobot_mww::owner_test_active())page.detail="Тест: ГоБот, вопрос";\n    }'
    change(app,old,new)
    old='} else if(line=="GOBOT_CHECK_PAUSE" && !gobot_turn_.Active() && !gobot_muted_) {'
    new='''} else if(line=="GOBOT_WAKE_TEST_ARM" && !gobot_turn_.Active() && !gobot_muted_) {
        const bool armed=gobot_mww::arm_owner_test(600,3);
        ESP_LOGI(TAG,"GOBOT_WAKE_TEST armed=%d left=%u production_qualified=%d",int(armed),gobot_mww::owner_test_remaining(),int(gobot_mww::qualified()));RenderGoBot();
    } else if(line=="GOBOT_WAKE_TEST_CANCEL") {
        gobot_mww::cancel_owner_test();ESP_LOGI(TAG,"GOBOT_WAKE_TEST cancelled=1");RenderGoBot();
    } else if(line=="GOBOT_CHECK_PAUSE" && !gobot_turn_.Active() && !gobot_muted_) {'''
    change(app,old,new)
    for path in (root/'CMakeLists.txt',main/'gobot_build_info.h'):change(path,'0.4.8-dev-reference-local-1',VERSION)
    (root/'owner-wake-template.json').write_text(json.dumps({'version':VERSION,'production_qualified':False,'owner_trial_compiled':True,
        'trial_default_active':False,'local_max_seconds':600,'local_max_attempts':3,'server_budget_and_acl_still_required':True,
        'prefix_ms':2000,'buffer_ms':12000,'model_slot_bytes':131072,'contains_personal_weights':False,'flashed':False},indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('isolated_reference_copy',type=Path);a=p.parse_args();prepare(a.isolated_reference_copy)
