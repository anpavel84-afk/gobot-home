"""One optional warm ECAPA process, bounded IPC; speaker identity never gates STT."""
import asyncio,base64,json,time
from uuid import uuid4
from .live_agents import ROOT
from .processes import AgentError,native_process,clean_environment

def quality(pcm,minimum=3):
    import numpy as np
    if len(pcm)<32000*minimum or len(pcm)%2:return {'state':'insufficient_audio','reason':'short_segment'}
    samples=np.frombuffer(pcm,dtype='<i2').astype(np.float32)/32768
    rms=float(np.sqrt(np.mean(samples*samples)))
    if rms<.003:return {'state':'insufficient_audio','reason':'too_quiet'}
    if float(np.mean(np.abs(samples)>.99))>.01:return {'state':'insufficient_audio','reason':'clipping'}
    frames=samples[:len(samples)//320*320].reshape(-1,320)
    energies=np.sqrt(np.mean(frames*frames,axis=1));p10,p90=np.percentile(energies,[10,90])
    if p90<.004 or p10>.8*p90:return {'state':'insufficient_audio','reason':'noise_or_no_speech_dynamics'}
    speech_seconds=float(np.sum(energies>max(.003,float(p10)*3)))*.02
    if speech_seconds<(2 if minimum<=3 else 4):return {'state':'insufficient_audio','reason':'insufficient_voiced_frames'}
    return {'state':'usable','seconds':len(pcm)/32000,'rms_dbfs':20*float(np.log10(max(rms,1e-9))),
            'estimated_speech_seconds':speech_seconds,'quality_policy':'experimental-energy-and-clipping-v2'}

class SpeakerEngine:
    def __init__(self):self.lock=asyncio.Lock();self.requests=asyncio.Queue(maxsize=2);self.worker=None
    def installed(self):return (ROOT/'.venv-speaker/Scripts/python.exe').exists() and (ROOT/'data/models/ecapa/embedding_model.ckpt').exists()
    async def run(self):
        try:
            env=clean_environment();env.update({'HF_HUB_OFFLINE':'1','HF_HOME':str(ROOT/'run/speaker-hf'),'OMP_NUM_THREADS':'2'})
            async with native_process([ROOT/'.venv-speaker/Scripts/python.exe',ROOT/'services/speaker/worker.py'],ROOT,env,discard_errors=True) as process:
                while True:
                    ident,pcm,future=await self.requests.get()
                    try:
                        process.stdin.write(json.dumps({'id':ident,'pcm':base64.b64encode(pcm).decode()}).encode()+b'\n');await process.stdin.drain()
                        line=await asyncio.wait_for(process.stdout.readline(),45)
                        obj=json.loads(line)
                        if obj.get('id')!=ident or 'embedding' not in obj:raise AgentError('speaker_embedding_unavailable')
                        if not future.done():future.set_result(obj)
                    except Exception:
                        if not future.done():future.set_exception(AgentError('speaker_embedding_unavailable'))
                        raise
                    finally:
                        # A warm worker must not retain the preceding household PCM between jobs.
                        pcm=b'';line=b'';obj=None;future=None
        except asyncio.CancelledError:raise
        except Exception:pass
        finally:
            while not self.requests.empty():
                _,_,future=self.requests.get_nowait()
                if not future.done():future.set_exception(AgentError('speaker_worker_stopped'))
    async def embed(self,pcm):
        if not self.installed():raise AgentError('speaker_model_not_installed')
        async with self.lock:
            if not self.worker or self.worker.done():self.worker=asyncio.create_task(self.run())
        future=asyncio.get_running_loop().create_future()
        try:self.requests.put_nowait((str(uuid4()),pcm,future))
        except asyncio.QueueFull:raise AgentError('speaker_busy')
        return await asyncio.wait_for(future,50)
    async def close(self):
        if self.worker:
            self.worker.cancel();await asyncio.gather(self.worker,return_exceptions=True)

class SpeakerIdentity:
    def __init__(self,family,engine=None):self.family=family;self.engine=engine or SpeakerEngine();self.jobs={};self.metrics=[]
    async def identify(self,pcm):
        started=time.perf_counter();check=quality(pcm)
        if check['state']!='usable':return {**check,'personal_authorized':False}
        if not await asyncio.to_thread(self.family.calibration):return {'state':'unknown','reason':'calibration_required','personal_authorized':False}
        try:
            encoded=await self.engine.embed(pcm)
            result=await asyncio.to_thread(self.family.identify,encoded['embedding'])
            result['identification_ms']=(time.perf_counter()-started)*1000
            self.metrics.append(result['identification_ms']);self.metrics=self.metrics[-200:]
            await asyncio.to_thread(self.family.memory.record_metrics,str(uuid4()),'ecapa',{'speaker_identity':result['identification_ms']})
            return result
        except AgentError as error:return {'state':'unknown','reason':error.code,'personal_authorized':False}
    def submit(self,pcm,device):
        # Expired/completed jobs release result metadata; no raw audio is retained on disk.
        now=time.monotonic()
        self.jobs={k:v for k,v in self.jobs.items() if now-v[2]<300 or not v[0].done()}
        if len(self.jobs)>32:return None
        ident=str(uuid4());task=asyncio.create_task(self.identify(pcm));self.jobs[ident]=(task,device,now)
        return ident
    def submit_recording(self,data,mime,speech,device):
        now=time.monotonic()
        self.jobs={k:v for k,v in self.jobs.items() if now-v[2]<300 or not v[0].done()}
        if len(self.jobs)>32:return None
        async def work():
            try:return await self.identify(await speech.decode(data,mime))
            except Exception:return {'state':'unknown','reason':'speaker_audio_unavailable','personal_authorized':False}
        ident=str(uuid4());self.jobs[ident]=(asyncio.create_task(work()),device,now);return ident
    def result(self,ident,device):
        entry=self.jobs.get(ident)
        if not entry or entry[1]!=device:return {'state':'unknown'}
        return entry[0].result() if entry[0].done() and not entry[0].cancelled() else {'state':'unknown','reason':'identity_pending','personal_authorized':False}
    async def enroll(self,profile,pcm,kind='enroll'):
        check=quality(pcm,minimum=6)
        if check['state']!='usable':raise AgentError(check['reason'])
        encoded=await self.engine.embed(pcm)
        await asyncio.to_thread(self.family.store,profile,encoded['embedding'],check['seconds'],kind)
        return {'stored':True,'raw_audio_saved':False,'quality':check}
    async def close(self):
        for task,_,_ in self.jobs.values():task.cancel()
        await asyncio.gather(*(item[0] for item in self.jobs.values()),return_exceptions=True)
        await self.engine.close()
