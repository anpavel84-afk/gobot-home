"""COPY current firmware -> guided calibration/USB timeout fix. No capture or flash."""
import argparse,hashlib,json,shutil
from pathlib import Path
from prepare_product import change
from guided_wake_plan import header,plan
HERE=Path(__file__).resolve().parent
VERSION='0.4.12-dev-guided-calibration-1'


def prepare(root,public_model):
    main=root/'main'
    if '0.4.11-dev-ref-parity-1' not in (root/'CMakeLists.txt').read_text():raise ValueError('Copy installed0.4.11 first')
    config=(main/'gobot_mww_config.h').read_text()
    if '#define GOBOT_WAKE_ROUTE 0' not in config or '#define GOBOT_WAKE_OWNER_TEST 0' not in config:raise ValueError('No wake/paid admission change in guided candidate')
    blob=public_model.read_bytes();old=(main/'gobot_mww.tflite').read_bytes()
    if len(blob)!=60912 or hashlib.sha256(blob).hexdigest()!='4ffc532e16b3e20b7ce09099338023b5af304a0e31bf537034bb03dd67a4c5f9':raise ValueError('Preserve installed public model')
    slot=blob+bytes(131072-len(blob))
    if len(old)!=131072 or (old!=slot and hashlib.sha256(old).hexdigest()!='1e26ad59e1a9a5773b0310fc03d5b689dfa575b7f1521aa63e9299239b27e2e4'):raise ValueError('Unexpected fixed public build slot')
    (main/'gobot_mww.tflite').write_bytes(slot) # Prior build embedded a public placeholder and patched this same public model locally.
    for name in ('gobot_raw_wake.cc','gobot_raw_wake.h','raw_wake_capture.h'):shutil.copy2(HERE/name,main/name)
    (main/'guided_wake_prompts.h').write_bytes(header().encode())
    change(main/'application.cc','page.value=gobot_raw_wake::label();page.detail="Без облака";','page.value=gobot_raw_wake::label();page.detail=gobot_raw_wake::detail();')
    change(main/'audio/audio_service.cc','bool AudioService::IsLocalScanRunning() const {return xEventGroupGetBits(event_group_) & kLocalScan;}',
        'bool AudioService::IsLocalScanRunning() const {auto bits=xEventGroupGetBits(event_group_);return (bits & kLocalScan) && !(bits & AS_EVENT_AUDIO_PROCESSOR_RUNNING) && !gobot_raw_wake::busy();}')
    for p in (root/'CMakeLists.txt',main/'gobot_build_info.h'):change(p,'0.4.11-dev-ref-parity-1',VERSION)
    (root/'guided-calibration.json').write_text(json.dumps({'version':VERSION,'previous_version':'0.4.11-dev-ref-parity-1','recording_default_active':False,'fresh_owner_recording_consent_required':True,'physical_touch_required':True,'guided_seconds':50,'guided_plan':plan(),'wake_model_unchanged':True,'production_qualified':False,'wake_route':False,'owner_trial_compiled':False,'paid_calls':0,'flashed':False},indent=2,ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('source_copy',type=Path);parser.add_argument('public_model',type=Path);args=parser.parse_args();prepare(args.source_copy,args.public_model)
