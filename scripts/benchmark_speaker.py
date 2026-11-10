"""Public fixture only: real local ECAPA timing, simulated network STT overlap."""
import asyncio,json,sys,time,wave
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'services/brain'))
from gobot.speaker import SpeakerEngine,quality
from gobot.metrics import percentiles
async def main():
    with wave.open(str(ROOT/'data/models/ecapa/example1.wav'),'rb') as wav:pcm=wav.readframes(wav.getnframes())
    engine=SpeakerEngine();durations=[];overlap=[];baseline=[]
    try:
        for index in range(13):
            started=time.perf_counter();task=asyncio.create_task(engine.embed(pcm))
            # A controlled 30ms mock STT tests scheduling only, not OpenAI latency.
            before=time.perf_counter();await asyncio.sleep(.03);overlap.append((time.perf_counter()-before)*1000)
            answer=await task;durations.append((time.perf_counter()-started)*1000)
            before=time.perf_counter();await asyncio.sleep(.03);baseline.append((time.perf_counter()-before)*1000)
    finally:await engine.close()
    result={'engine':'SpeechBrain 1.1.2 ECAPA-TDNN / Torch 2.11.0 CPU, 2 threads',
            'fixture':'public pinned model example1.wav; not family audio','quality':quality(pcm),
            'cold_embedding_ipc_ms':durations[0],'warm_embedding_ipc_ms':percentiles(durations[1:]),
            'simulated_stt_while_embedding_ms':percentiles(overlap[1:]),'simulated_stt_baseline_ms':percentiles(baseline[1:]),
            'real_identification_accuracy_measured':False,'real_family_identification_p50_p95':None,
            'paid_api_requests':0,'interpretation':'Embedding/IPC latency is measured; overlap uses a 30ms mock STT, not real end-to-end voice.'}
    (ROOT/'docs/speaker-benchmarks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':asyncio.run(main())
