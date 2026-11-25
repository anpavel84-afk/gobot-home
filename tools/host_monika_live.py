"""Owner-authorized physical Monika pilot; existing A Gateway + B factory.
One bounded process owns isolated WSS 18799 and COM3. No service installation,
production config, paid models, reflash, PC mic, audio files or transcripts.
STOP_MONIKA.cmd requests graceful HOST_OFF through the current serial owner.
"""
from __future__ import annotations
import argparse,asyncio,contextlib,json,os,re,ssl,sys,threading,time
from pathlib import Path
from datetime import datetime,timezone

sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
MAIN=ROOT.parent/'GoBotHome'
B=ROOT.parent/'GoBotHome-wake-lab'
B_SITE=ROOT.parent/'HOST-B-lab'/'.venv'/'Lib'/'site-packages'
MODELS=ROOT.parent/'HOST-B-lab'/'models'
PRIVATE=MAIN/'data'/'hardware'/'gobot-v1'
RUN=ROOT/'run'/'host-a'/'monika-live'
sys.path.insert(0,str(ROOT/'services'/'voice'))
sys.path.insert(0,str(ROOT/'tools'))
# Reuse HOST-A's existing private serial tooling without installing production dependencies.
sys.path.append(str(ROOT/'run'/'host-a'/'rc1-preflight-venv'/'Lib'/'site-packages'))
from host_monika_runtime import make_owner_authorized_factory,source_version
from host_wake_contract import AudioChunk
from host_rc1_test_listener import prepare,forbidden_paid
from gobot_device_gateway import Gateway
from host_local_command import OfflineTimeResponder

STATUS=re.compile(r'GOBOT_STATUS version=(\S+) wifi=(\d) enrolled=(\d) muted=(\d) phase=(\d).* upload=(\d)')
COUNTERS=('received_packets','pcm_frames','received_span_s','wake_activations',
          'screen_acks','cue_acks','local_command_jobs','local_command_recognized',
          'local_command_unrecognized','local_command_failures','completed_replies',
          'manual_touch_activations','manual_touch_stops','downlink_packets',
          'fixture_playback_started_ack','fixture_playback_drained_ack',
          'max_queue_frames','max_queue_age_ms','ignored_early_device_finishes',
          'provider_calls','last_failure_code','abrupt_device_close')

def utc():return datetime.now(timezone.utc).isoformat(timespec='seconds')

def write_status(data):
    # On Windows, an external read of status.json can momentarily deny an
    # atomic replace. Telemetry must never terminate the live COM3/WSS owner.
    temp=RUN/'status.tmp'
    payload=json.dumps(data,ensure_ascii=True,indent=2)
    for attempt in range(8):
        try:
            temp.write_text(payload,encoding='utf8')
            temp.replace(RUN/'status.json')
            return
        except PermissionError:
            if attempt==7:
                print('MONIKA_STATUS_WRITE_CONTENDED_NONFATAL',flush=True)
                return
            time.sleep(.04*(attempt+1))


def uart_owner(stop,state,lock):
    # Vosk wheel's venv supplies existing pyserial only for this process.
    import serial
    from serial.tools import list_ports
    found=[p for p in list_ports.comports() if p.device.upper()=='COM3']
    if len(found)!=1 or found[0].vid!=0x303A or found[0].pid!=0x1001:
        with lock:state['error']='EXPECTED_SPOTPEAR_COM3_NOT_FOUND'
        stop.set();return
    enabled=False;uart=None
    try:
        # Exclusive access fails instead of taking COM3 from another process.
        uart=serial.Serial('COM3',115200,timeout=.25,write_timeout=1,
                           dsrdtr=False,rtscts=False)
        uart.dtr=False;uart.rts=False
        with lock:state['com_owned']=True
        if stop.wait(16):return
        uart.reset_input_buffer();uart.write(b'GOBOT_STATUS\n')
        deadline=time.monotonic()+8
        valid=False
        while not stop.is_set() and time.monotonic()<deadline:
            line=uart.readline().decode('utf8',errors='ignore')
            match=STATUS.search(line)
            if match:
                version,wifi,enrolled,muted,phase,upload=match.groups()
                with lock:state.update(version=version,wifi=int(wifi),enrolled=int(enrolled))
                valid=(version=='0.4.13-dev-host-a-rc1-r3' and wifi=='1'
                       and enrolled=='1' and muted=='0' and phase=='0' and upload=='0')
                break
        if not valid:raise RuntimeError('DEVICE_NOT_IDLE_WIFI_ENROLLED_R3')
        uart.write(b'GOBOT_HOST_ON\n');enabled=True
        with lock:state['host_on_sent']=True
        ready_deadline=time.monotonic()+40;last_query=time.monotonic()
        while not stop.is_set():
            line=uart.readline().decode('utf8',errors='ignore')
            if 'GOBOT_HOST_READY' in line:
                with lock:
                    state['host_ready']=True
                    state['ready_count']=state.get('ready_count',0)+1
                print('SPOTPEAR_MONIKA_HOST_READY',flush=True)
            if 'GOBOT_HOST_MODE OFF' in line:
                with lock:state['host_ready']=False;state['local_restored']=True
            if 'GOBOT_HOST_RC1_FAULT' in line:
                with lock:state['host_faults']=state.get('host_faults',0)+1
            match=STATUS.search(line)
            if match:
                with lock:state['wifi']=int(match.group(2));state['enrolled']=int(match.group(3))
            with lock:is_ready=state.get('host_ready',False)
            if not is_ready and time.monotonic()>ready_deadline:
                raise RuntimeError('SPOTPEAR_HOST_HANDSHAKE_NOT_OBSERVED')
            if time.monotonic()-last_query>30:
                uart.write(b'GOBOT_STATUS\n');last_query=time.monotonic()
    except Exception as exc:
        with lock:state['error']=type(exc).__name__+':'+str(exc)[:130]
        print('MONIKA_UART_ERROR',type(exc).__name__,flush=True)
        stop.set()
    finally:
        if uart is not None:
            if enabled:
                # HOST_OFF can be rejected while the driver drains output.
                # Retry only this volatile command, never flash/reset/NVS.
                end=time.monotonic()+12;last_off=0
                while time.monotonic()<end:
                    try:
                        if time.monotonic()-last_off>2:
                            uart.write(b'GOBOT_HOST_OFF\n');last_off=time.monotonic()
                        line=uart.readline().decode('utf8',errors='ignore')
                        if 'GOBOT_HOST_MODE OFF' in line:
                            with lock:state.update(host_ready=False,local_restored=True)
                            print('SPOTPEAR_RETURNED_LOCAL',flush=True);break
                    except Exception:break
            uart.close()
        with lock:state['com_owned']=False


async def main(args):
    if not args.owner_direct_monika:raise PermissionError('EXPLICIT_OWNER_DIRECT_REQUIRED')
    if not 60<=args.seconds<=14400:raise ValueError('BOUNDED_PILOT_REQUIRED')
    RUN.mkdir(parents=True,exist_ok=True)
    import serial  # fail before listener creation if existing USB tooling is missing
    if not hasattr(serial,'Serial'):raise RuntimeError('PYSERIAL_NOT_AVAILABLE')
    # No PC mic, no extra name test. Preflight loads actual accepted code/types.
    factory=make_owner_authorized_factory(B,MODELS,B_SITE)
    detector=await asyncio.to_thread(factory)
    version=source_version(B)
    for n in range(5):
        detector.feed_chunk(AudioChunk(bytes(1920),'compatibility',n*960,time.monotonic_ns()))
    detector.reset()
    if args.preflight_only:
        print(json.dumps({'preflight':'PASS','b_commit':version,
                          'detector':'vosk-small-ru-0.22','phrase_id':'monika',
                          'factory':'HOST-B.make_monika_factory','audio_source':'NONE',
                          'paid_calls':0}),flush=True)
        return
    import psutil
    for proc in psutil.process_iter(['pid','name','cmdline']):
        if proc.pid==os.getpid():continue
        cmd=proc.info['cmdline'] or []
        if any(str(c).endswith(('host_rc1_sustained_usb.py','host_rc1_usb_free_smoke.py',
                               'host_rc1_human_usb.py','host_rc1_test_listener.py')) for c in cmd):
            raise RuntimeError('EXISTING_A_TEST_OWNER_PID_'+str(proc.pid))
    lockfile=RUN/'owner.lock'
    if lockfile.exists():
        existing=json.loads(lockfile.read_text())
        if psutil.pid_exists(existing['pid']):raise RuntimeError('MONIKA_STAND_ALREADY_RUNNING')
        lockfile.unlink()
    with lockfile.open('x') as file:json.dump({'pid':os.getpid()},file)
    (RUN/'STOP').unlink(missing_ok=True)
    stop=threading.Event();guard=threading.Lock();device={'host_ready':False,'local_restored':False}
    uart_thread=None;gateway=None
    try:
        original=json.loads((PRIVATE/'gateway.json').read_text(encoding='utf8'))
        cfg=prepare(original,18799)
        cfg['host_wake']['monika_trial']=True
        cfg['host_wake']['free_downlink_fixture']=False
        # Reuse one already-loaded detector sequentially per sole gateway connection.
        def existing_factory():detector.reset();return detector
        gateway=Gateway(cfg,'NEVER_USED',client_factory=forbidden_paid,
                        host_detector_factory=existing_factory)
        gateway.save_stats=lambda:None;gateway.respond=forbidden_paid
        gateway.reserve_manual_turn=forbidden_paid
        gateway.host_local_command_responder=OfflineTimeResponder(
            MAIN/'data'/'models'/'faster-whisper-small',PRIVATE/'irina.onnx')
        tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.minimum_version=ssl.TLSVersion.TLSv1_2
        tls.load_cert_chain(str(PRIVATE/'server.pem'),str(PRIVATE/'server.key'))
        from websockets.asyncio.server import serve
        async with serve(gateway.handle,cfg['bind'],18799,ssl=tls,max_size=16384,
                         max_queue=8,ping_interval=20,ping_timeout=10,
                         open_timeout=8,close_timeout=2,compression=None):
            uart_thread=threading.Thread(target=uart_owner,args=(stop,device,guard),daemon=False)
            uart_thread.start()
            begin=time.monotonic();last_print=-30
            while not stop.is_set() and time.monotonic()-begin<args.seconds:
                if (RUN/'STOP').exists():stop.set();break
                with guard:physical=dict(device)
                h=gateway.stats.get('host',{})
                info={'updated_utc':utc(),'pid':os.getpid(),'running':True,
                      'b_commit':version,'detector':'vosk-small-ru-0.22','phrase_id':'monika',
                      'source':'physical_Spotpear_Opus16_PCM16','trial_port':18799,
                      'seconds_remaining':max(0,round(args.seconds-(time.monotonic()-begin))),
                      'device':physical,'connection_active':gateway.active,
                      'counters':{k:h[k] for k in COUNTERS if k in h},
                      'detector_frames':detector.frames,'detector_events':detector.events,
                      'paid_calls':0,'audio_saved':False,'transcripts_saved':False,
                      'acoustic_acceptance':'NOT_MEASURED_OWNER_EXPERIMENTAL',
                      'voice_stop':'NOT_ENABLED_MANUAL_STOP_ONLY'}
                write_status(info)
                if time.monotonic()-begin-last_print>=15:
                    last_print=time.monotonic()-begin
                    print(json.dumps({'event':'MONIKA_LIVE','host':physical.get('host_ready'),
                                      'active':gateway.active,'frames':h.get('received_packets',0),
                                      'wake':h.get('wake_activations',0),
                                      'answers':h.get('completed_replies',0),
                                      'error':h.get('last_failure_code')}),flush=True)
                await asyncio.sleep(1)
            stop.set()
            if uart_thread is not None:await asyncio.to_thread(uart_thread.join,15)
    finally:
        stop.set()
        if uart_thread is not None and uart_thread.is_alive():
            await asyncio.to_thread(uart_thread.join,16)
        with guard:physical=dict(device)
        write_status({'updated_utc':utc(),'pid':os.getpid(),'running':False,
                      'device':physical,'b_commit':version,'paid_calls':0,
                      'audio_saved':False,'transcripts_saved':False})
        lockfile.unlink(missing_ok=True)

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--owner-direct-monika',action='store_true')
    p.add_argument('--preflight-only',action='store_true')
    p.add_argument('--seconds',type=int,default=7200)
    asyncio.run(main(p.parse_args()))
