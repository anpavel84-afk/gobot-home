"""One NEW explicitly consented pre-AFE sample. Does not flash or call APIs.

Requires raw-capture candidate installed separately, and physical touch after arm.
No generic serial log is saved. Lossy/partial/interleaved output fails closed.
"""
import argparse,io,json,sys,time,uuid,wave
from pathlib import Path
from raw_wake_protocol import Decoder
from sample_retention import paths
ROOT=Path(__file__).resolve().parents[3]

def prepare_guided_usb(device):
    for _ in range(2):
        device.reset_input_buffer();device.write(b'GOBOT_RAW_USB_PREPARE\n');deadline=time.monotonic()+2
        while time.monotonic()<deadline:
            if device.readline(4096).strip()==b'GOBOT_RAW_USB_READY':return
    raise RuntimeError('Guided capture firmware/USB preparation not acknowledged')


def main(port,seconds,consent,protocol,persistent_selected_model=False):
    if not consent:raise ValueError('A fresh recording consent is required; old samples are consumed')
    if protocol=='field_failed_wake_recheck' and seconds>30:raise ValueError('Field recheck is limited to30 seconds')
    if protocol=='guided_wake8' and seconds!=50:raise ValueError('Guided capture requires exactly50 seconds')
    if persistent_selected_model and protocol!='guided_wake8':raise ValueError('Persistent selected-model consent is separate and guided-only')
    sys.path.append(str(ROOT/'data/hardware/venv/Lib/site-packages'))
    import serial
    from serial.tools.list_ports import comports
    boards=[p for p in comports() if (p.vid,p.pid)==(0x303a,0x1001)]
    if len(boards)!=1 or boards[0].device.lower()!=port.lower():raise ValueError('Expected one selected Espressif USB device')
    # Import retention setup without invoking its legacy processed-audio recorder.
    from record_owner_sample import deletion_task
    sys.path.insert(0,str(ROOT/'services/brain'))
    from gobot.secrets_store import _dpapi
    nonce=uuid.uuid4().hex;decoder=Decoder(nonce,seconds)
    target,meta=paths(nonce);target.parent.mkdir(parents=True,exist_ok=True)
    expiry=time.time()+23*3600
    meta.write_text(json.dumps({'expires_at':expiry,'capture_domain':'mono_pcm16_pre_afe',
        'raw_seconds_limit':seconds,'protocol':protocol,'consent':'Owner explicit NEW raw USB sample','cloud_transfer':False,
        'persistent_selected_model_consent':persistent_selected_model,'selected_model_scope':'same_enrolled_column_only' if persistent_selected_model else 'same_as_raw_sample','consent_consumed':False}))
    if protocol=='guided_wake8':
        from guided_wake_plan import plan
        data=json.loads(meta.read_text());data['capture_plan']=plan();meta.write_text(json.dumps(data))
    def status(event,**extra):
        data=json.loads(meta.read_text());data.update({'capture_state':event,'state_at':time.time(),**extra})
        meta.write_text(json.dumps(data)) # Numeric/control events only, no speech or PCM.
    deletion_task(nonce,expiry) # BEFORE arm, failure leaves no active recorder.
    device=serial.Serial();device.port=port;device.baudrate=115200;device.timeout=.2
    device.dtr=False;device.rts=False;started=False
    try:
        device.open()
        if protocol=='guided_wake8':prepare_guided_usb(device)
        device.reset_input_buffer();command='GOBOT_RAW_GUIDED_ARM' if protocol=='guided_wake8' else 'GOBOT_RAW_ARM'
        device.write(f'{command} {nonce} {seconds}\n'.encode())
        deadline=time.monotonic()+125;pending=bytearray();guided_ack=False
        while not decoder.done:
            if time.monotonic()>deadline:raise TimeoutError('Bounded USB capture expired')
            pending.extend(device.read(4096))
            if len(pending)>32768:raise ValueError('Oversized USB line')
            while b'\n' in pending:
                line,_,rest=pending.partition(b'\n');pending=bytearray(rest);line=line.strip()
                ack='GOBOT_RAW_GUIDED_ARMED' if protocol=='guided_wake8' else 'GOBOT_RAW_ARMED'
                if line==f'{ack} {nonce} {seconds}'.encode():
                    guided_ack=protocol=='guided_wake8'
                    status('armed',physical_start_ack=False)
                    print('RAW_USB_ARMED physical_touch_required=1 no_cloud=1',flush=True)
                    continue # Validated control ACK is not PCM framing.
                if line==f'GOBOT_RAW_STARTED {nonce}'.encode():
                    started=True;status('recording',physical_start_ack=True,consent_consumed=True)
                    if protocol=='guided_wake8' and not guided_ack:raise ValueError('Guided mode not acknowledged before physical start')
                    deadline=time.monotonic()+seconds+25
                    print('RAW_USB_STARTED',flush=True)
                decoder.line(line)
        if not started:raise ValueError('Physical start not acknowledged')
        with io.BytesIO() as memory:
            with wave.open(memory,'wb') as out:
                out.setnchannels(1);out.setsampwidth(2);out.setframerate(16000);out.writeframes(decoder.pcm)
            target.write_bytes(_dpapi(memory.getvalue()))
        status('complete_crc_verified',recorded_seconds=seconds)
        print(json.dumps({'sample_id':nonce,'seconds':seconds,'encrypted':True,'capture_domain':'mono_pcm16_pre_afe'}))
    except Exception as error:
        status('capture_failed' if started else 'ended_without_start',error_type=type(error).__name__,received_pcm_bytes=len(decoder.pcm))
        raise
    finally:
        try:
            if device.is_open:device.write(b'GOBOT_RAW_CANCEL\n')
        finally:device.close();decoder.clear()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--port',required=True);p.add_argument('--seconds',type=int,choices=range(15,61),required=True)
    p.add_argument('--protocol',choices=['wake10_questions','hard_negatives_4_wakes','field_failed_wake_recheck','guided_wake8'],required=True)
    p.add_argument('--allow-persistent-selected-model',action='store_true')
    p.add_argument('--new-recording-consent',action='store_true');a=p.parse_args();main(a.port,a.seconds,a.new_recording_consent,a.protocol,a.allow_persistent_selected_model)
