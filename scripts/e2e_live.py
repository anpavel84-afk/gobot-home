"""Single owner-approved live probe. Never called by pytest or service startup."""
import argparse,asyncio,json,sys,time,wave
from pathlib import Path
from uuid import uuid4
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'services/brain'))

async def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('provider',choices=['codex','gemini','openai-voice'])
    parser.add_argument('--owner-approved',action='store_true')
    args=parser.parse_args()
    if not args.owner_approved:parser.error('Explicit owner approval is required before quota/API use')
    if args.provider=='openai-voice':
        from gobot.audio import Speech,TTS_MODEL
        start=time.perf_counter();first=None;parts=[]
        async for pcm,rate in Speech().synthesize('Привет! Я Гобот.',paid_consent=True):
            if first is None:first=(time.perf_counter()-start)*1000
            parts.append(pcm)
        with wave.open(str(ROOT/'data/openai-voice-owner-approved.wav'),'wb') as out:
            out.setnchannels(1);out.setsampwidth(2);out.setframerate(rate);out.writeframes(b''.join(parts))
        result={'provider':'openai','model':TTS_MODEL,'real':True,'audio_bytes':sum(map(len,parts)),
                'first_chunk_ms':first,'total_ms':(time.perf_counter()-start)*1000,'iphone_playback_verified':False}
    else:
        import httpx
        turn=str(uuid4());conversation='live-approved-'+str(uuid4());start=time.perf_counter();deltas=[];terminal=None;first=None
        # Full product transport: private HTTPS -> Brain -> signed Bridge -> installed CLI.
        async with httpx.AsyncClient(trust_env=False,timeout=150) as client:
            async with client.stream('POST','https://plan.tailffc57c.ts.net:18786/api/chat/stream',
                headers={'Origin':'https://plan.tailffc57c.ts.net:18786'},json={
                    'text':'Привет! Ответь одним коротким предложением на русском языке',
                    'mode':args.provider,'conversation_id':conversation,'turn_id':turn,
                    'usage_consent':True,'speak':False}) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith('data: '):continue
                    item=json.loads(line[6:]);kind=item['type']
                    if kind=='text_delta':
                        if first is None:first=(time.perf_counter()-start)*1000
                        deltas.append(item['data']['text'])
                    if kind in {'final','error','cancelled'}:terminal=item
            history=(await client.get('https://plan.tailffc57c.ts.net:18786/api/history/'+conversation)).json()
        if not terminal or terminal['type']!='final' or terminal['data'].get('mock'):
            print(json.dumps({'provider':args.provider,'real_verified':False,'terminal':terminal},ensure_ascii=False))
            raise SystemExit(1)
        text=''.join(deltas).strip()
        result={'provider':args.provider,'real':True,'deltas':len(deltas),'first_delta_ms':first,
                'total_ms':(time.perf_counter()-start)*1000,'text':text,
                'sqlite_persisted':any(m['role']=='assistant' and m['content']==text for m in history['messages'])}
    path=ROOT/'docs/real-e2e.json'
    reports=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    reports[args.provider]=result;path.write_text(json.dumps(reports,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':asyncio.run(main())
