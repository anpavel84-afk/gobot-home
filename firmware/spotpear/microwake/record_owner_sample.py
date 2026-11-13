"""One explicitly consented <=60s sample. PLAN-only DPAPI, timed deletion, no APIs."""
import asyncio,io,json,os,ssl,subprocess,sys,time,uuid,wave
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'services/voice'),str(ROOT/'firmware/spotpear'),str(ROOT/'services/brain')]
from fast_start_probe import stop_owned,restore
from gobot_device_gateway import Gateway,PRIVATE
from gobot.secrets_store import _dpapi
from websockets.asyncio.server import serve
import httpx
from sample_retention import paths

def deletion_task(ident,expires):
    executable=str(ROOT/'.venv/Scripts/python.exe');script=str(Path(__file__).with_name('sample_retention.py'))
    assert "'" not in executable+script
    command=("$a=New-ScheduledTaskAction -Execute '"+executable+"' -Argument '\""+script+'\" '+ident+"';"
        "$t=New-ScheduledTaskTrigger -Once -At ([DateTimeOffset]::FromUnixTimeSeconds("+str(int(expires))+").LocalDateTime);"
        "$s=New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries;"
        "Register-ScheduledTask -TaskName 'GoBot-WakeSample-"+ident+"' -Action $a -Trigger $t -Settings $s -Description 'Delete one Owner-consented GoBot wake sample' -ErrorAction Stop | Out-Null")
    result=subprocess.run(['powershell','-NoProfile','-NonInteractive','-Command',command],capture_output=True,timeout=20)
    if result.returncode:raise RuntimeError('Automatic sample deletion task could not be registered; no recording started')

async def run(ident):
    target,metadata=paths(ident);target.parent.mkdir(parents=True,exist_ok=True)
    expires=json.loads(metadata.read_text())['expires_at']
    metadata.write_text(json.dumps({'expires_at':expires,'raw_seconds_limit':50,'consent':'Owner explicit local sample','cloud_transfer':False}))
    config=json.loads((PRIVATE/'gateway.json').read_text());config={**config,'mode':'duplex_test'}
    complete=asyncio.Event();claimed=False
    class Recorder(Gateway):
        async def respond(self,ws,send,capture,turn):
            nonlocal claimed
            if claimed:await ws.close(1008,'One sample only');return
            claimed=True;pcm=bytearray()
            try:
                await send({'type':'gobot_media_ready'})
                print('LOCAL_RECORDING_STARTED duration_limit=50 no_cloud=1',flush=True)
                started=asyncio.get_running_loop().time()
                while asyncio.get_running_loop().time()-started<50:
                    frame=await capture.recv()
                    pcm.extend(frame.to_ndarray().astype('<i2',copy=False).tobytes())
                    if len(pcm)>=16000*2*50:break
                with io.BytesIO() as memory:
                    with wave.open(memory,'wb') as out:
                        out.setnchannels(1);out.setsampwidth(2);out.setframerate(16000);out.writeframes(pcm)
                    sealed=_dpapi(memory.getvalue())
                target.write_bytes(sealed)
                print(json.dumps({'recorded_seconds':len(pcm)/32000,'encrypted':True,'local_only':True,'expires_at':expires,'sample_id':ident}),flush=True)
                await ws.close(1000,'Local wake sample complete')
            finally:
                pcm[:]=bytes(len(pcm));capture.buffer[:]=bytes(len(capture.buffer));capture.buffer.clear();complete.set()
    def no_http(**kw):
        def reject(request):raise AssertionError('No HTTP requests in local recorder')
        return httpx.AsyncClient(**kw,transport=httpx.MockTransport(reject))
    gateway=Recorder(config,'',client_factory=no_http)
    tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.load_cert_chain(PRIVATE/'server.pem',PRIVATE/'server.key')
    async with serve(gateway.handle,config['bind'],config['port'],ssl=tls,max_size=16384,max_queue=8,compression=None):
        gateway.save_stats();print('LOCAL_RECORDER_READY touch_to_start=1 model_calls=0 standby_recording=0',flush=True)
        await asyncio.wait_for(complete.wait(),600)
        for _ in range(50):
            if not gateway.active:break
            await asyncio.sleep(.1)

if __name__=='__main__':
    ident=uuid.uuid4().hex
    # Retention registration precedes taking the production listener.
    target,metadata=paths(ident);target.parent.mkdir(parents=True,exist_ok=True)
    metadata.write_text(json.dumps({'expires_at':time.time()+23*3600}))
    deletion_task(ident,time.time()+23*3600)
    stop_owned()
    try:asyncio.run(run(ident))
    finally:restore()
