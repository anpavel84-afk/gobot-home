import asyncio,json
import pytest
from gobot.antigravity import AntigravityEvents,environment
from gobot.processes import AgentError
from gobot.brain import Service
from gobot.models import ChatRequest

def test_agy_stream_filter_and_no_duplicate_final():
    parser=AntigravityEvents();out=[]
    events=[{'event':'init','init':{'permission_mode':'strict'}},
            {'event':'step_update','step_update':{'step_type':'tool','tool_info':{'output':'PRIVATE'}}},
            {'event':'step_update','step_update':{'step_type':'thinking','text_delta':'REASONING'}},
            {'event':'step_update','step_update':{'step_type':'agent_response','state':'ACTIVE','text_delta':'При'}},
            {'event':'step_update','step_update':{'step_type':'agent_response','state':'DONE','text_delta':'вет'}},
            {'event':'result','result':{'status':'SUCCESS','response':'Привет','usage':{'private':'SECRET'}}}]
    for item in events:out+=parser.parse(item)
    assert ''.join(out)=='Привет' and parser.completed
    assert parser.parse(events[-1])==[]
    with pytest.raises(AgentError):AntigravityEvents().parse({'event':'init','init':{'permission_mode':'always-proceed'}})

def test_google_admission_does_not_fall_back_without_approval(settings,monkeypatch):
    import gobot.brain as brain
    monkeypatch.setattr(brain,'agent_status',lambda *a:{'antigravity':{'available':False,'reason':'oauth_login_required'},'codex':{'available':True}})
    calls=[]
    async def fake(settings,req,context):calls.append(req.provider);yield 'Ответ фикстуры Codex.'
    monkeypatch.setattr(brain,'bridge_stream',fake)
    async def run():
        service=Service(settings);req=ChatRequest(text='Спроси Google',mode='google',usage_consent=True)
        await service.prepare(req);items=[x async for x in service.events(req)]
        assert calls==[] and items[-1].type=='error'
        assert items[-1].data['code']=='oauth_login_required'
    asyncio.run(run())

def test_agy_failure_before_text_fallback_only_once(settings,monkeypatch):
    import gobot.brain as brain
    monkeypatch.setattr(brain,'agent_status',lambda *a:{'antigravity':{'available':True},'codex':{'available':True}})
    calls=[]
    async def fake(settings,req,context):
        calls.append(req.provider)
        if req.provider=='antigravity':raise AgentError('agent_network_failed')
        yield 'Ответ фикстуры.'
    monkeypatch.setattr(brain,'bridge_stream',fake)
    async def run():
        service=Service(settings);req=ChatRequest(text='Вопрос',mode='google',usage_consent=True,expensive_fallback_approved=True)
        await service.prepare(req);items=[x async for x in service.events(req)]
        assert calls==['antigravity','codex'] and items[-1].type=='final'
    asyncio.run(run())

def test_agy_failure_after_partial_does_not_mix_models(settings,monkeypatch):
    import gobot.brain as brain
    monkeypatch.setattr(brain,'agent_status',lambda *a:{'antigravity':{'available':True},'codex':{'available':True}})
    calls=[]
    async def fake(settings,req,context):calls.append(req.provider);yield 'Начало';raise AgentError('agent_network_failed')
    monkeypatch.setattr(brain,'bridge_stream',fake)
    async def run():
        service=Service(settings);req=ChatRequest(text='Вопрос',mode='google',usage_consent=True)
        await service.prepare(req);items=[x async for x in service.events(req)]
        assert calls==['antigravity'] and items[-1].type=='error'
    asyncio.run(run())

def test_gemini_live_retired_and_agy_no_api_keys():
    from gobot.live_agents import GeminiLiveAdapter
    async def run():
        with pytest.raises(AgentError,match='retired'):await anext(GeminiLiveAdapter().stream('x',{}))
    asyncio.run(run())
    env=environment()
    assert all(name not in env for name in ['GEMINI_API_KEY','GOOGLE_API_KEY','OPENAI_API_KEY'])
    assert env['AGY_CLI_DISABLE_AUTO_UPDATE']=='true'
