"""Free HTTPS product probe: real local STT/offline TTS, explicit mock LLM."""
import asyncio,json,time
from pathlib import Path
from uuid import uuid4
import httpx
ROOT=Path(__file__).resolve().parents[1]
BASE='https://plan.tailffc57c.ts.net:18786'

async def main():
    conversation='browser-fixture-'+str(uuid4())
    started=time.perf_counter();types=[];sequences=[];first_audio=None
    async with httpx.AsyncClient(trust_env=False,timeout=150) as client:
        response=await client.post(BASE+'/api/audio/transcribe?provider=whisper',headers={'Origin':BASE,'Content-Type':'audio/wav'},content=(ROOT/'data/tts-real-smoke.wav').read_bytes())
        response.raise_for_status();stt=response.json()
        async with client.stream('POST',BASE+'/api/chat/stream',headers={'Origin':BASE},json={
            'text':stt['text'],'conversation_id':conversation,'mode':'mock','tts_provider':'denis','speak':True}) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith('data: '):continue
                event=json.loads(line[6:]);types.append(event['type'])
                if event['type']=='audio_chunk':
                    sequences.append(event['data']['seq'])
                    if first_audio is None:first_audio=(time.perf_counter()-started)*1000
                if event['type']=='final':assert event['data']['mock'] is True
        history=(await client.get(BASE+'/api/history/'+conversation)).json()
    assert sequences and sequences==list(range(len(sequences))) and types[-1]=='final'
    assert len(history['messages'])==2
    result={'transport':'private Tailscale HTTPS, TLS verified','stt':stt,'llm':'explicit mock',
            'tts':'real local Piper Denis, explicitly selected offline reserve','ordered_audio_chunks':len(sequences),
            'first_audio_including_stt_ms':first_audio,'total_ms':(time.perf_counter()-started)*1000,
            'sqlite_persisted':True,'paid_requests':0,'iphone_microphone_verified':False,'iphone_playback_verified':False}
    (ROOT/'docs/browser-free-e2e.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':asyncio.run(main())
