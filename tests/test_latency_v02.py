import asyncio,json,subprocess
from pathlib import Path
import pytest
from gobot.telemetry import Trace,Traces,scope,mark,client_trace
from gobot.brain import Service
from gobot.models import ChatRequest
from gobot.pipeline import voiced_events

def test_ac26_clock_domains_acl_unknowns_and_no_content(tmp_path):
    clock=[1.];trace=Trace('trace-fixture',clock=lambda:clock[0]);trace.mark('stt_submit',text='PRIVATE',model='fixture')
    clock[0]=2.;trace.mark('stt_final');trace.mark('stt_final')
    store=Traces(tmp_path);store.save('owner',trace)
    assert store.read('other','trace-fixture')==[]
    sample=store.read('owner','trace-fixture')[0]
    assert sample['events'][-1]['ms']==1000 and len(sample['events'])==2
    assert 'PRIVATE' not in json.dumps(sample) and sample['unknown_stages']
    with pytest.raises(ValueError):client_trace({'trace_id':'x','events':[{'name':'prompt','ms':1}]})
    with pytest.raises(ValueError):client_trace({'trace_id':'x','events':[{'name':'input_closed','ms':float('nan')}]})

def test_ac26_full_mock_voice_trace_has_first_sentence_and_audio(settings):
    async def run():
        service=Service(settings);req=ChatRequest(text='Привет',mode='mock',remember=False,trace_id='ac26')
        class Voice:
            async def synthesize(self,*args,**kw):yield b'\1\0'*30,24000
        events=[e async for e in voiced_events(service,Voice(),req)]
        trace=events[-1]['data']['telemetry'];names=[e['name'] for e in trace['events']]
        for name in ['brain_queue_start','brain_queue_end','context_start','context_end','router_end','first_assistant_delta','sentence_ready','formatter_start','formatter_end','tts_segment_submit','tts_first_audio_payload']:assert name in names,name
        assert names.index('first_assistant_delta')<names.index('tts_first_audio_payload')
        assert service.traces.read(req.device_id,'ac26')
    asyncio.run(run())

def test_ac25_progress_is_not_paid_tts_or_useful_answer(settings,monkeypatch):
    from gobot.models import event
    async def run():
        service=Service(settings);req=ChatRequest(text='Привет',remember=False);spoken=[]
        async def source(*a):
            yield event(req,'sentence_ready',text='Подбираю визуальный материал.',representation='progress')
            yield event(req,'sentence_ready',text='Содержательный ответ.')
            yield event(req,'final',text='Содержательный ответ.',provider='mock')
        class Voice:
            async def synthesize(self,text,*a,**kw):spoken.append(text);yield b'\1\0',24000
        monkeypatch.setattr(service,'events',source)
        events=[e async for e in voiced_events(service,Voice(),req)]
        assert spoken==['Содержательный ответ.']
    asyncio.run(run())

def test_ac23_25_feedback_controller_node():
    root=Path(__file__).resolve().parents[1]
    result=subprocess.run(['node','tests/feedback_timing.cjs'],cwd=root,capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stderr

def test_ac25_26_shared_audio_scheduler_node():
    root=Path(__file__).resolve().parents[1]
    result=subprocess.run(['node','tests/client_playback_timing.cjs'],cwd=root,capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stderr

def test_ac26_late_client_delivery_cannot_replace_newer_trace(tmp_path):
    store=Traces(tmp_path)
    for revision,events in [(2,[{'name':'first_answer_playback','ms':9000}]),(1,[])]:
        store.save('owner',client_trace({'trace_id':'reorder','revision':revision,'events':events}))
    assert store.read('owner','reorder')[0]['revision']==2

def test_trace_metadata_retry_keeps_request_idempotent(settings):
    from gobot.memory import Memory,Conflict
    memory=Memory(settings.db)
    for remember in (True,False):
        request=ChatRequest(text='Повторная доставка',mode='mock',remember=remember,trace_id='first-trace')
        assert memory.start(request) is None
        memory.finish(request,'completed','Ответ.','mock',[])
        replay=memory.start(request.model_copy(update={'trace_id':'second-trace'}))
        assert replay['result']=='Ответ.'
        with pytest.raises(Conflict):memory.start(request.model_copy(update={'text':'Другой запрос'}))

def test_ac36_docs_only_sync_preserves_code_base():
    root=Path(__file__).resolve().parents[1]
    result=subprocess.run(['git','diff','--name-only','bd487fff1e6cb88cdc34e3fc53ebd15dbde1cb11','96e0f3d19dfcf57b09f711dd8c5ce45f0ef580a4'],cwd=root,capture_output=True,text=True,check=True)
    assert result.stdout.strip()=='docs/GOBOT_HOME_TARGET_SYSTEM.md'

def test_ac26_gateway_stt_brain_tts_share_trace_without_network(settings,monkeypatch):
    import io,wave,base64,httpx
    from contextlib import asynccontextmanager
    from fastapi.testclient import TestClient
    import gobot.brain as brain
    import gobot.browser as browser
    import gobot.stt as stt
    from gobot.audio import Speech
    class WS:
        def __init__(self):self.messages=asyncio.Queue()
        async def send(self,raw):
            msg=json.loads(raw)
            if msg['type']=='session.update':await self.messages.put({'type':'session.updated'})
            if msg['type']=='response.create':
                await self.messages.put({'type':'response.output_audio.delta','delta':base64.b64encode(b'\1\0'*50).decode()})
                await self.messages.put({'type':'response.done','response':{'status':'completed'}})
        async def recv(self):return json.dumps(await self.messages.get())
    @asynccontextmanager
    async def connector(*a,**k):yield WS()
    monkeypatch.setattr(brain,'Speech',lambda:Speech(api_key='fixture',connector=connector))
    monkeypatch.setattr(stt,'load_openai_key',lambda:'fixture')
    app=brain.create_app(settings);real_client=httpx.AsyncClient
    class LocalOnly(httpx.AsyncBaseTransport):
        async def handle_async_request(self,request):
            if request.url.host=='api.openai.com':
                assert request.url.path=='/v1/audio/transcriptions'
                return httpx.Response(200,json={'text':'Привет'},request=request)
            assert request.url.host=='127.0.0.1'
            return await httpx.ASGITransport(app=app).handle_async_request(request)
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kwargs:real_client(**{**kwargs,'transport':LocalOnly()}))
    wav=io.BytesIO()
    with wave.open(wav,'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(b'\0\0'*8000)
    with TestClient(browser.create_browser_app(settings),base_url=browser.ORIGIN,client=('100.120.201.115',200)) as client:
        headers={'Origin':browser.ORIGIN,'Content-Type':'audio/wav'}
        response=client.post('/api/audio/transcribe?trace_id=full-fixture&paid_consent=true',headers=headers,content=wav.getvalue())
        assert response.status_code==200,response.text
        stt_result=response.json();assert stt_result['telemetry']['trace_id']=='full-fixture'
        response=client.post('/api/chat/stream',headers={'Origin':browser.ORIGIN},json={'text':stt_result['text'],'mode':'mock','trace_id':'full-fixture','remember':False,'speak':True,'paid_tts_consent':True})
        events=[json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
        assert events[-1]['type']=='final' and any(e['type']=='audio_chunk' for e in events)
        names={e['name'] for e in events[-1]['data']['telemetry']['events']}
        assert {'stt_upload_first','stt_final','stt_provider_submit','first_assistant_delta','chunker_sentence_ready','tts_handshake_end','audio_transport_send'}<=names
        traces=client.get('/api/telemetry/full-fixture').json()['traces']
        assert {t['clock_domain'] for t in traces}>={'brain','gateway-stt','gateway-chat'}
        assert all(not t['contains_content'] for t in traces)
