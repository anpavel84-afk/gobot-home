"""One NEW explicitly consented pre-AFE sample. Does not flash or call APIs.

Requires raw-capture candidate installed separately, and physical touch after arm.
No generic serial log is saved. Lossy/partial/interleaved output fails closed.
"""
import argparse,io,json,sys,time,uuid,wave
from pathlib import Path
from raw_wake_protocol import Decoder
from sample_retention import paths
ROOT=Path(__file__).resolve().parents[3]

def main(port,seconds,consent,protocol):
    if not consent:raise ValueError('A fresh recording consent is required; old samples are consumed')
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
        'raw_seconds_limit':seconds,'protocol':protocol,'consent':'Owner explicit NEW raw USB sample','cloud_transfer':False}))
    deletion_task(nonce,expiry) # BEFORE arm, failure leaves no active recorder.
    device=serial.Serial();device.port=port;device.baudrate=115200;device.timeout=.2
    device.dtr=False;device.rts=False;device.open()
    try:
        device.reset_input_buffer();device.write(f'GOBOT_RAW_ARM {nonce} {seconds}\n'.encode())
        deadline=time.monotonic()+160;pending=bytearray();started=False
        while not decoder.done:
            if time.monotonic()>deadline:raise TimeoutError('Bounded USB capture expired')
            pending.extend(device.read(4096))
            if len(pending)>32768:raise ValueError('Oversized USB line')
            while b'\n' in pending:
                line,_,rest=pending.partition(b'\n');pending=bytearray(rest);line=line.strip()
                if line==f'GOBOT_RAW_ARMED {nonce} {seconds}'.encode():print('RAW_USB_ARMED physical_touch_required=1 no_cloud=1',flush=True)
                if line==f'GOBOT_RAW_STARTED {nonce}'.encode():
                    started=True;print('RAW_USB_STARTED',flush=True)
                decoder.line(line)
        if not started:raise ValueError('Physical start not acknowledged')
        with io.BytesIO() as memory:
            with wave.open(memory,'wb') as out:
                out.setnchannels(1);out.setsampwidth(2);out.setframerate(16000);out.writeframes(decoder.pcm)
            target.write_bytes(_dpapi(memory.getvalue()))
        print(json.dumps({'sample_id':nonce,'seconds':seconds,'encrypted':True,'capture_domain':'mono_pcm16_pre_afe'}))
    finally:
        try:device.write(b'GOBOT_RAW_CANCEL\n')
        finally:device.close();decoder.clear()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--port',required=True);p.add_argument('--seconds',type=int,choices=range(15,61),required=True)
    p.add_argument('--protocol',choices=['wake10_questions','hard_negatives_4_wakes'],required=True)
    p.add_argument('--new-recording-consent',action='store_true');a=p.parse_args();main(a.port,a.seconds,a.new_recording_consent,a.protocol)
