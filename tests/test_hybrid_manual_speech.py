"""Manual Owner speech HTTP paths with fake provider, real budget ledger. No API."""
import asyncio,io,wave
import httpx,pytest
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from hybrid_host import setup_host,block_paid,browser_host

@pytest.mark.parametrize('kind',['stt','tts'])
def test_manual_owner_speech_uses_existing_budget_and_blocks_next_attempt(tmp_path,monkeypatch,kind):
    from gobot.audio import Speech
    from gobot.stt import OpenAIRecognition
    h=setup_host(tmp_path);block_paid(monkeypatch,h);calls=[]
    policy=h['realtime'].owner_testing.policy()
    h['realtime'].owner_testing.policy_path.write_text(policy.model_copy(update={'api_estimate_usd_per_day':1}).model_dump_json())
    async def decode(*a,**kw):return b'\0'*6400
    async def fake_file(self,data,mime,*,paid_consent):
        assert paid_consent and mime=='audio/wav'
        with wave.open(io.BytesIO(data)) as f:assert f.getframerate()==16000
        calls.append('stt');return {'text':'Который час?','provider':'fixture','final':True}
    async def fake_synthesis(self,text,provider,voice,*,paid_consent):
        assert paid_consent and voice=='marin';calls.append('tts');yield b'\0'*2400,24000
    monkeypatch.setattr(Speech,'decode',decode);monkeypatch.setattr(OpenAIRecognition,'file',fake_file)
    monkeypatch.setattr(Speech,'synthesize',fake_synthesis)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=h['backend']),base_url='http://test',headers=h['auth']) as c:
            async def speech():
                if kind=='stt':
                    return await c.post('/api/v1/next/transcribe',params={k:v for k,v in {**h['scope'],'paid_consent':True}.items() if k!='profile_epoch'},content=b'fixture',headers={'Content-Type':'audio/wav'})
                opened=(await c.post('/api/v1/next/open',json=h['scope'])).json()['conversation_id']
                op=(await c.post('/api/v1/next/operation',json={**h['scope'],'conversation_id':opened})).json()['operation_id']
                await c.post('/api/v1/next/dispatch',json={**h['scope'],'input':{'conversation_id':opened,'operation_id':op,'text':'Который час?'}})
                return await c.post('/api/v1/next/speech',json={**h['scope'],'conversation_id':opened,'operation_id':op,'paid_consent':True})
            first=await speech();assert first.status_code==200,first.text
            assert (await speech()).status_code==200
            second=await speech();assert second.status_code==403 and second.json()['detail']=='owner_api_estimate_limit'
        assert calls==[kind,kind] and not h['paid_calls']
        with h['realtime'].owner_testing.connect() as db:
            assert db.execute('SELECT origin,cost,pending FROM attempts').fetchall()==[('web_'+kind,.5,1)]*2
        await h['live'].shutdown();await h['realtime'].shutdown()
    asyncio.run(run())

def test_gateway_non_json_speech_failure_is_a_controlled_json_error(tmp_path,monkeypatch):
    h=setup_host(tmp_path);block_paid(monkeypatch,h);h['backend']=FastAPI()
    @h['backend'].post('/api/v1/next/transcribe')
    async def fail():return PlainTextResponse('fixture upstream failure',status_code=500)
    gateway=browser_host(monkeypatch,h)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway),base_url='http://fixture') as c:
            r=await c.post('/api/next/transcribe?paid_consent=true',content=b'fixture')
            assert r.status_code==502 and r.json()=={'detail':'preview_backend_invalid_response'}
        assert not h['paid_calls'];await h['live'].shutdown();await h['realtime'].shutdown()
    asyncio.run(run())
