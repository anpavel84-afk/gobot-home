import asyncio,json
import pytest
from fastapi.testclient import TestClient
from gobot.brain import create_app,Service
from gobot.models import ChatRequest
from gobot.memory import Memory,Conflict
from gobot.providers import SentenceBuffer

def run(coro):return asyncio.run(coro)
async def collect(service,req):
    replay=await service.prepare(req)
    return [e async for e in service.events(req,replay)]
def test_health_auth_stream_memory_replay(settings):
    app=create_app(settings)
    with TestClient(app) as client:
        assert client.get('/healthz').status_code==200
        assert client.get('/readyz').json()['voice_hardware_ready'] is False
        assert client.get('/api/v1/status').status_code==401
        headers={'Authorization':'Bearer '+settings.api_token}
        req={'text':'Привет','conversation_id':'c1','turn_id':'t1','provider':'mock'}
        response=client.post('/api/v1/chat/stream',headers=headers,json=req)
        assert response.status_code==200
        items=[json.loads(x[6:]) for x in response.text.splitlines() if x.startswith('data: ')]
        assert items[-1]['type']=='final'
        assert ''.join(x['data']['text'] for x in items if x['type']=='text_delta').strip()==items[-1]['data']['text']
        sentences=[x['data']['text'] for x in items if x['type']=='sentence_ready']
        assert sentences==['Это mock-ответ GoBot на русском.','Контекст разговора сохранён.']
        assert {x['conversation_id'] for x in items}=={'c1'}
        replay=client.post('/api/v1/chat',headers=headers,json=req).json()['events']
        assert len(replay)==1 and replay[0]['data']['replayed']
        assert client.post('/api/v1/chat',headers=headers,json={**req,'text':'другое'}).status_code==409
        status=client.get('/api/v1/turns/t1',headers=headers).json()
        assert status['status']=='completed' and 'result' not in status
    memory=Memory(settings.db)
    context=memory.context(ChatRequest(text='снова',conversation_id='c1'))
    assert len(context['messages'])==2 and context['summary']

def test_restart_context_cross_model_and_facts(settings):
    first=ChatRequest(text='Первый вопрос',conversation_id='shared',provider='mock')
    service=Service(settings);run(collect(service,first))
    memory=Memory(settings.db);memory.add_fact('local-test','Разрешённый факт',True)
    with pytest.raises(ValueError):memory.add_fact('local-test','Нет согласия',False)
    next_req=ChatRequest(text='Спроси ChatGPT, как он думает об этом',conversation_id='shared',provider='mock')
    ctx=memory.context(next_req)
    assert ctx['messages'][0]['content']=='Первый вопрос' and ctx['facts']==['Разрешённый факт']
    result=run(collect(Service(settings),next_req))
    assert result[-1].data['trace'][0]['reason']=='explicit_second_opinion'
    memory.purge(conversation='shared');assert memory.context(next_req)['messages']==[]
    memory.forget_facts('local-test');assert memory.context(next_req)['facts']==[]

def test_recover_running_turn(settings):
    memory=Memory(settings.db);req=ChatRequest(text='x');memory.start(req);Memory(settings.db).recover()
    assert memory.status(req.turn_id)['status']=='cancelled'

def test_ownership_and_concurrent_turn_collision(settings):
    m=Memory(settings.db);r=ChatRequest(text='a',conversation_id='owned');m.start(r)
    with pytest.raises(Conflict):m.start(r)
    with pytest.raises(Conflict):m.start(ChatRequest(text='b',conversation_id='owned',device_id='foreign'))

def test_timeout_cancel_disconnect_backpressure(settings,monkeypatch):
    import gobot.brain as brain
    async def slow(*args):
        yield 'Начало. '
        await asyncio.sleep(5)
        yield 'Конец.'
    monkeypatch.setattr(brain,'fast_stream',slow)
    async def exercise():
        service=Service(settings);req=ChatRequest(text='slow');await service.prepare(req);iterator=service.events(req)
        assert (await anext(iterator)).type=='tool_status'
        assert (await anext(iterator)).type=='text_delta'
        assert (await anext(iterator)).type=='sentence_ready'
        # Consumer controls iteration: no queue/prefetch can run the full response.
        service.running[req.turn_id].set()
        rest=[x async for x in iterator];assert rest[-1].type=='cancelled'
        assert service.memory.status(req.turn_id)['status']=='cancelled'
        req=ChatRequest(text='disconnect');await service.prepare(req);it=service.events(req)
        await anext(it);await it.aclose();assert service.memory.status(req.turn_id)['status']=='cancelled'
        settings.timeout=.03;req=ChatRequest(text='timeout');items=await collect(service,req)
        assert items[-1].type=='error' and items[-1].data['code']=='timeout'
    run(exercise())

def test_parallel_sessions(settings):
    async def exercise():
        service=Service(settings)
        results=await asyncio.gather(*(collect(service,ChatRequest(text='Привет',device_id='d'+str(i))) for i in range(4)))
        assert all(r[-1].type=='final' for r in results)
        assert len({r[0].conversation_id for r in results})==4
    run(exercise())

@pytest.mark.parametrize('field,value',[('fast_provider','invalid'),('asr','invalid'),('tts','invalid'),('vad','invalid'),('bridge_url','http://192.168.3.1:80')])
def test_config_validation(settings,field,value):
    setattr(settings,field,value)
    with pytest.raises(ValueError):settings.validate()

def test_sentence_chunk_boundary():
    b=SentenceBuffer();out=[]
    for d in ['Привет, ','мир','! Как ','дела','?']:out+=b.feed(d)
    out+=b.feed('',True);assert out==['Привет, мир!','Как дела?']
