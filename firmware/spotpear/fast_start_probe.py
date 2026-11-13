"""Owner-authorized physical board / fake backend only; never a model call."""
import asyncio,contextlib,json,os,re,ssl,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'services/voice')]
from night_preview import idle
from gobot_device_gateway import Gateway,PRIVATE
from websockets.asyncio.server import serve
import psutil,httpx
sys.path.append(str(ROOT/'data/hardware/venv/Lib/site-packages'))
import serial
from serial.tools import list_ports

def stop_owned():
    idle();script=(ROOT/'services/voice/gobot_device_gateway.py').resolve()
    candidates={p.pid:p for p in psutil.process_iter(['cmdline']) if any(a.endswith('gobot_device_gateway.py') and Path(a).resolve()==script for a in p.info['cmdline'] or []) and Path(p.cwd()).resolve()==ROOT}
    listeners={c.pid for c in psutil.net_connections('tcp') if c.laddr and c.laddr.port==18789 and not c.raddr}
    owned=[p for pid,p in candidates.items() if pid in listeners]
    assert len(owned)==1
    p=owned[0];parent=p.parent();group=[p]+([parent] if parent and parent.pid in candidates else [])
    for process in group:process.terminate()
    assert not psutil.wait_procs(group,timeout=5)[1]

def restore():
    env=os.environ.copy();env['PYTHONUTF8']='1'
    with (PRIVATE/'realtime-b-runtime.log').open('ab') as out:
        subprocess.Popen([str(ROOT/'.venv/Scripts/python.exe'),str(ROOT/'services/voice/gobot_device_gateway.py'),'--config',str(PRIVATE/'gateway.json')],cwd=ROOT,env=env,stdin=subprocess.DEVNULL,stdout=out,stderr=out,creationflags=0x08000000)

async def run():
    config=json.loads((PRIVATE/'gateway.json').read_text());config={**config,'mode':'duplex_test'}
    results=[];scenario='delayed_ready';started=asyncio.Event();finished=asyncio.Event()
    class LocalGateway(Gateway):
        async def respond(self,ws,send,capture,turn):
            result={'scenario':scenario};results.append(result);started.set()
            try:
                if scenario=='cancel_before_ready':
                    await asyncio.sleep(1);await ws.close(1000,'Free local cancellation');return
                await asyncio.sleep(2 if scenario=='delayed_ready' else 10)
                result['samples_before_ready']=capture.received_samples
                await send({'type':'gobot_media_ready'})
                end=asyncio.get_running_loop().time()+2
                while asyncio.get_running_loop().time()<end:await capture.recv()
                result['received_samples']=capture.received_samples
                result['peak_backlog_ms']=capture.peak_backlog_bytes//32
                await ws.close(1000,'Free local capture check complete')
            finally:
                result['received_samples']=capture.received_samples
                finished.set()
    def no_http(**kwargs):
        def reject(request):raise AssertionError('No HTTP/API allowed in physical free fixture')
        return httpx.AsyncClient(**kwargs,transport=httpx.MockTransport(reject))
    gateway=LocalGateway(config,'',client_factory=no_http)
    tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.load_cert_chain(PRIVATE/'server.pem',PRIVATE/'server.key')
    ports=[p for p in list_ports.comports() if (p.vid,p.pid)==(0x303a,0x1001)]
    assert len(ports)==1
    usb=serial.Serial(port=None,baudrate=115200,timeout=.1);usb.port=ports[0].device;usb.dtr=usb.rts=False;usb.open()
    capture_ms=[];statuses=[];pending=b'';monitor_task=None
    async def monitor():
        nonlocal pending
        next_poll=0
        while True:
            if time.monotonic()>next_poll:usb.write(b'\nGOBOT_STATUS\n');next_poll=time.monotonic()+.5
            pending+=await asyncio.to_thread(usb.read,4096)
            lines=pending.split(b'\n');pending=lines.pop()[-8192:]
            for line in lines:
                found=re.search(rb'GOBOT_LOCAL_CAPTURE started_ms=(\d+)',line)
                if found:capture_ms.append(int(found[1]))
                found=re.search(rb'GOBOT_STATUS version=0\.4\.5-dev-fast-start-1 wifi=(\d+) enrolled=(\d+) muted=(\d+) phase=(\d+) wake_running=(\d+) wake_words=(\d+) upload=(\d+)',line)
                if found:statuses.append(tuple(map(int,found.groups())))
    try:
        async with serve(gateway.handle,config['bind'],config['port'],ssl=tls,max_size=16384,max_queue=8,compression=None):
            monitor_task=asyncio.create_task(monitor())
            for name in ('delayed_ready','overflow','cancel_before_ready'):
                scenario=name;started.clear();finished.clear()
                deadline=time.monotonic()+6
                while not statuses or statuses[-1][3]!=0:
                    assert time.monotonic()<deadline,'Board not idle';await asyncio.sleep(.1)
                count=len(statuses);usb.write(b'\nGOBOT_MEDIA_BEGIN\n')
                await asyncio.wait_for(started.wait(),10)
                await asyncio.wait_for(finished.wait(),14)
                count=len(statuses) # Require a NEW idle report after this turn ended.
                deadline=time.monotonic()+5
                while gateway.active or len(statuses)<=count or statuses[-1][3]!=0:
                    assert time.monotonic()<deadline,'Board cleanup not confirmed';await asyncio.sleep(.1)
                results[-1]['idle_upload']=statuses[-1][6]
                print(json.dumps(results[-1]),flush=True)
                await asyncio.sleep(1.5)
            assert len(capture_ms)==3
            assert results[0].get('samples_before_ready')==0 and results[0]['received_samples']>=16000*3
            assert results[1]['received_samples']==0 and results[2]['received_samples']==0
            assert all(r['idle_upload']==0 for r in results)
            evidence={'activation':'USB diagnostic, NOT human touch','local_capture_started_ms':capture_ms,'scenarios':results,'model_calls':0,'raw_audio_saved':False,'first_syllable_human_acceptance':False}
            (PRIVATE/'fast-start-free-evidence.json').write_text(json.dumps(evidence,indent=2));print(json.dumps(evidence),flush=True)
    finally:
        (PRIVATE/'fast-start-free-partial.json').write_text(json.dumps({'local_capture_started_ms':capture_ms,'scenarios':results,'raw_audio_saved':False,'model_calls':0},indent=2))
        if monitor_task:
            monitor_task.cancel();await asyncio.gather(monitor_task,return_exceptions=True)
        usb.close()

if __name__=='__main__':
    stop_owned()
    try:asyncio.run(run())
    finally:restore()
