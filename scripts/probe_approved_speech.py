"""Exactly the three short probes previously approved by the owner. No retries.
Durable attempt markers prevent accidental reruns after crashes/failures.
Only synthetic public test speech is uploaded. Never prints raw provider errors.
"""
import asyncio,json,sys,time,wave,io
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'services/brain'))
from gobot.audio import Speech,TTS_MODEL
from gobot.stt import OpenAIRecognition,FILE_MODEL,LIVE_MODEL
from gobot.processes import AgentError
from gobot.speech_formatter import SpeechFormatter

MARKER=ROOT/'run/owner-approved-three-speech-probes.json'
async def main():
    if '--owner-approved-three-probes' not in sys.argv:raise SystemExit('Explicit owner authorization flag required')
    state=json.loads(MARKER.read_text(encoding='utf-8')) if MARKER.exists() else {}
    fixture=ROOT/'data/tts-real-smoke.wav';speech=Speech();recognition=OpenAIRecognition()
    raw=fixture.read_bytes()
    with wave.open(io.BytesIO(raw),'rb') as recording:
        duration=recording.getnframes()/recording.getframerate()
    if not 2<=duration<=4:raise SystemExit('Expected the approved approximately 3-second synthetic fixture')
    def mark(name,status,**data):
        state[name]={'status':status,'recorded':time.time(),**data};MARKER.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8')
    if 'file_stt' not in state:
        mark('file_stt','attempted',model=FILE_MODEL,seconds=duration)
        try:
            result=await recognition.file(raw,'audio/wav',paid_consent=True)
            mark('file_stt','completed',**result)
        except AgentError as e:mark('file_stt','failed',code=e.code)
    if 'live_stt' not in state:
        import numpy as np
        decoded=await speech.decode(raw,'audio/wav')
        # decode returns 16k mono PCM; live transport explicitly requires 24k.
        source=np.frombuffer(decoded,dtype='<i2')
        pcm=np.interp(np.arange(0,len(source),2/3),np.arange(len(source)),source).astype('<i2').tobytes()
        async def chunks():
            for offset in range(0,len(pcm),4800):
                yield pcm[offset:offset+4800];await asyncio.sleep(.1)
        mark('live_stt','attempted',model=LIVE_MODEL,seconds=duration)
        interim=0;first_before_commit=False;final=None
        try:
            async for item in recognition.live(chunks(),paid_consent=True):
                if item['type']=='stt_partial':interim+=1
                if item['type']=='stt_final':final=item['data']
            mark('live_stt','completed',**(final or {}),partial_events=interim)
        except AgentError as e:mark('live_stt','failed',code=e.code,partial_events=interim)
    if 'tts' not in state:
        text=SpeechFormatter().format('Привет! Я Гобот, твой домашний помощник.')
        mark('tts','attempted',model=TTS_MODEL,voice='marin')
        started=time.perf_counter();first=None;parts=[];rate=24000
        try:
            async for pcm,rate in speech.synthesize(text,'openai','marin',paid_consent=True):
                if first is None:first=(time.perf_counter()-started)*1000
                parts.append(pcm)
            with wave.open(str(ROOT/'data/openai-voice-owner-approved.wav'),'wb') as output:
                output.setnchannels(1);output.setsampwidth(2);output.setframerate(rate);output.writeframes(b''.join(parts))
            mark('tts','completed',model=TTS_MODEL,voice='marin',first_audio_ms=first,total_ms=(time.perf_counter()-started)*1000,audio_seconds=sum(map(len,parts))/2/rate,pcm_chunks=len(parts))
        except AgentError as e:mark('tts','failed',code=e.code)
    report={'authorization':'Owner approved one file STT, one live STT, one short TTS; no retries','results':state,'actual_api_cost':'not returned by transport; consult OpenAI usage dashboard','iphone_playback_verified':False}
    (ROOT/'docs/openai-speech-probes.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':asyncio.run(main())
