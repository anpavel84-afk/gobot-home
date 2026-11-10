"""Free HTTPS trace smoke. STT/LLM mocks, TTS off; never an audible latency result."""
import asyncio,io,json,sqlite3,time,wave
from pathlib import Path
from uuid import uuid4
import httpx
ROOT=Path(__file__).resolve().parents[1]
BASE='https://plan.tailffc57c.ts.net:18786'

async def main():
    ident='latency-fixture-'+str(uuid4());conversation='temporary-'+str(uuid4());headers={'Origin':BASE}
    wav=io.BytesIO()
    with wave.open(wav,'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(b'\0\0'*3200)
    start=time.perf_counter();events=[{'name':'input_closed','ms':0}]
    def mark(name):events.append({'name':name,'ms':round((time.perf_counter()-start)*1000,3)})
    async with httpx.AsyncClient(trust_env=False,timeout=30) as client:
        for asset in ['/device','/turn-trace.js']:
            r=await client.get(BASE+asset);r.raise_for_status()
            if asset.endswith('.wav'):
                with wave.open(io.BytesIO(r.content)) as w:assert w.getframerate()==22050 and 0<w.getnframes()/22050<1.5
        start=time.perf_counter();mark('upload_start')
        response=await client.post(BASE+'/api/audio/transcribe',params={'provider':'mock','trace_id':ident},headers={**headers,'Content-Type':'audio/wav'},content=wav.getvalue());response.raise_for_status();transcript=response.json();mark('stt_final_received')
        assert transcript['provider']=='mock'
        mark('chat_submit');first=False;final=None
        async with client.stream('POST',BASE+'/api/chat/stream',headers=headers,json={'text':transcript['text'],'mode':'mock','trace_id':ident,'conversation_id':conversation,'remember':False,'speak':False,'usage_consent':False}) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith('data: '):continue
                item=json.loads(line[6:])
                if item['type']=='text_delta' and not first:mark('first_text');first=True
                if item['type']=='final':final=item['data']
                assert item['type']!='audio_chunk'
        assert final and final['mock']
        result=await client.post(BASE+'/api/telemetry/'+ident,headers=headers,json={'events':events,'revision':1});result.raise_for_status()
        traces=(await client.get(BASE+'/api/telemetry/'+ident)).json()['traces']
    assert {t['clock_domain'] for t in traces}>={'brain','gateway-chat','gateway-stt','client_monotonic'}
    with sqlite3.connect(ROOT/'data/gobot.sqlite') as db:count=db.execute('SELECT count(*) FROM messages WHERE conversation_id=?',(conversation,)).fetchone()[0]
    assert count==0
    report={'kind':'free HTTPS mock trace smoke, not speech performance','client':'Python HTTP driver, no physical browser','trace_id':ident,'traces':traces,
            'persistent_test_messages':count,'paid_requests':0,'cli_model_requests':0,'tts_enabled':False,
            'first_answer_audible_ms':None,'iphone_verified':False}
    (ROOT/'docs/latency-fixture-v02.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'clock_domains':[t['clock_domain'] for t in traces],'stage_events':sum(len(t['events']) for t in traces),'paid_requests':0,'persistent_test_messages':count,'audible_latency':'not measured'},ensure_ascii=False))

if __name__=='__main__':asyncio.run(main())
