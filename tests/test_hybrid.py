import asyncio,json,time,io,wave
from concurrent.futures import ThreadPoolExecutor
import pytest,httpx
from gobot.hybrid_contract import PreviewInput,PlaybackAck
from gobot.hybrid import Frame
from gobot.weather_answer import degrees,finite
from gobot.story_player import Stories
from gobot.voice_library import cache_key,VoiceLibrary
from gobot.hybrid_skills import manifests
from hybrid_fixtures import make,dispatch,timer_count

@pytest.fixture(autouse=True)
def paid_egress_denied(monkeypatch):
    from gobot.realtime_provider import RealtimeProvider
    from gobot.live_provider import LiveProvider
    from gobot.live_backend import LiveBackend
    from gobot.stt import OpenAIRecognition
    from gobot.audio import Speech
    attempts=[]
    async def deny(*a,**kw):attempts.append(True);raise AssertionError('paid egress forbidden')
    async def deny_audio(*a,**kw):attempts.append(True);raise AssertionError('paid TTS forbidden');yield b'',24000
    for cls,name in [(RealtimeProvider,'create'),(LiveProvider,'create'),(LiveBackend,'answer'),(OpenAIRecognition,'file')]:monkeypatch.setattr(cls,name,deny)
    monkeypatch.setattr(Speech,'synthesize',deny_audio)
    yield attempts
    assert not attempts

def test_real_timer_replay_and_separate_intent(settings):
    brain,h,scope,c=make(settings)
    async def run():
        op=h.issue(c.id,scope);body=PreviewInput(conversation_id=c.id,operation_id=op,text='Поставь таймер на пять минут')
        first=await h.dispatch(body,scope);second=await h.dispatch(body,scope)
        assert first.approved and second.replay and timer_count(brain)==1
        with pytest.raises(ValueError,match='payload_conflict'):await h.dispatch(body.model_copy(update={'text':'Поставь таймер на десять минут'}),scope)
        await dispatch(h,scope,c,body.text);assert timer_count(brain)==2
    asyncio.run(run())

def test_pending_slot_escape_and_late_yes(settings):
    brain,h,scope,c=make(settings)
    async def run():
        assert (await dispatch(h,scope,c,'Поставь таймер')).route_type=='CLARIFY_SLOT'
        assert (await dispatch(h,scope,c,'На пять')).results[0].verified_data['duration_seconds']==300
        await dispatch(h,scope,c,'Поставь таймер');clock=await dispatch(h,scope,c,'Который час?')
        assert clock.route_type=='EXECUTE_TOOL'
        assert (await dispatch(h,scope,c,'Да')).route_type=='CLARIFY_SLOT'
        assert timer_count(brain)==1
    asyncio.run(run())

def test_decline_clears_pending_without_starting_timer(settings):
    brain,h,scope,c=make(settings)
    async def run():
        await dispatch(h,scope,c,'Поставь таймер')
        result=await dispatch(h,scope,c,'Не надо')
        assert result.route_type=='MEDIA_CONTROL'
        assert (await dispatch(h,scope,c,'На пять')).route_type=='CLARIFY_SLOT'
        assert timer_count(brain)==0
    asyncio.run(run())

@pytest.mark.parametrize('text',['Не ставь таймер','Как поставить таймер?','Я купил таймер',
    'Поставь таймер на пять минут и удали мои файлы','Поставь таймер, только если завтра дождь',
    'Поставь таймер на пять или десять минут','Поставь таймер на три минуты, нет, на пять',
    'Не включай свет, расскажи о лампах','Что значит «поставь таймер»?'])
def test_whole_phrase_guards_precede_side_effects(settings,text):
    brain,h,scope,c=make(settings)
    asyncio.run(dispatch(h,scope,c,text));assert timer_count(brain)==0

def test_two_equal_timers_are_two_logical_actions(settings):
    brain,h,scope,c=make(settings)
    result=asyncio.run(dispatch(h,scope,c,'Поставь два одинаковых таймера по пять минут'))
    assert timer_count(brain)==2 and len({r.action_id for r in result.results})==2

def test_weather_scope_followup_topic_ttl(settings):
    brain,h,scope,c=make(settings)
    async def run():
        today=await dispatch(h,scope,c,'Какая сейчас погода?')
        assert today.answer.display_data['frame']['metadata']['facts']['temperature']=='14.7'
        assert 'пятнадцат' in today.answer.speech_text
        tomorrow=await dispatch(h,scope,c,'А завтра?')
        assert tomorrow.answer.canonical_facts['days'][0]['date']=='2026-11-14'
        assert 'Днём до' in tomorrow.answer.speech_text
        await dispatch(h,scope,c,'Который час?')
        assert (await dispatch(h,scope,c,'А завтра?')).route_type=='CLARIFY_SLOT'
        await dispatch(h,scope,c,'Какая погода?');c.frame.expires=h.clock()-1
        assert (await dispatch(h,scope,c,'А завтра?')).route_type=='CLARIFY_SLOT'
    asyncio.run(run())

@pytest.mark.parametrize('value',[-.4,-.5,-1,-2,-5,0,1,2,5,11,21,22,25,14.7])
def test_temperature_rounding_sign_and_inflections(value):
    text=degrees(value,prefix='около')
    assert text and 'градус' in text
    if value<0:assert 'минус' in text
    assert 'минус' not in degrees(0)

@pytest.mark.parametrize('value',[None,float('nan'),float('inf'),'invalid'])
def test_missing_is_not_zero(value):assert finite(value) is None and 'нет данных' in degrees(value)

def test_epoch_replay_and_unauthorized_operation(settings):
    brain,h,scope,c=make(settings);op=h.issue(c.id,scope)
    async def run():
        body=PreviewInput(conversation_id=c.id,operation_id=op,text='Поставь таймер на пять минут')
        for wrong in [(scope[0],'another',None),(scope[0],scope[1],'new-epoch')]:
            with pytest.raises(PermissionError):await h.dispatch(body,wrong)
        with pytest.raises(PermissionError):await h.dispatch(body.model_copy(update={'operation_id':'forged'}),scope)
        await h.dispatch(body.model_copy(update={'truncated':True}),scope)
        assert timer_count(brain)==0
    asyncio.run(run())

def test_concurrent_duplicate_http_semantics(settings):
    brain,h,scope,c=make(settings)
    async def run():
        op=h.issue(c.id,scope);body=PreviewInput(conversation_id=c.id,operation_id=op,text='Поставь таймер на пять минут')
        results=await asyncio.gather(h.dispatch(body,scope),h.dispatch(body,scope))
        assert sum(r.replay for r in results)==1 and timer_count(brain)==1
    asyncio.run(run())

def test_atomic_timer_receipt_survives_restarted_tool_instance(settings):
    brain,h,scope,c=make(settings);req=h.request(c,'timer','turn').model_copy(update={'device_id':h.tool_owner(scope)})
    first=brain.tools.start_timer_once(req,300,'server-action')
    from gobot.local_tools import LocalTools
    other=LocalTools(brain.memory);second=other.start_timer_once(req,300,'server-action')
    assert first.widget==second.widget and timer_count(brain)==1
    with pytest.raises(ValueError):other.start_timer_once(req,600,'server-action')

def test_story_ack_context_has_no_future_and_rejects_forgery():
    store=Stories();scope=('owner','client',None);job=store.create(scope,fixture=True)
    raw=store.fixture_audio(job,0)
    with wave.open(io.BytesIO(raw)) as f:assert f.getframerate()==24000
    base=dict(client_id='client',stream_id=job.id,segment_id='0',epoch=1,position_seconds=0)
    with pytest.raises(ValueError):store.ack(job,PlaybackAck(**{**base,'event':'drained','position_seconds':1.2}))
    store.ack(job,PlaybackAck(**base,event='started'))
    store.ack(job,PlaybackAck(**{**base,'event':'drained','position_seconds':1.2}))
    ctx=store.heard_context(job);assert len(ctx['heard_segments'])==1 and job.segments[-1] not in ctx['summary']
    with pytest.raises(ValueError):store.ack(job,PlaybackAck(**{**base,'client_id':'other','event':'started'}))
    job.epoch+=1
    with pytest.raises(ValueError):store.ack(job,PlaybackAck(**base,event='started'))

def test_voice_key_separates_semantics_and_privacy():
    assert cache_key('1 °C')!=cache_key('-1 °C')
    assert cache_key('1.0 °C')!=cache_key('1 °C')
    assert cache_key('Текст',privacy_scope='one')!=cache_key('Текст',privacy_scope='two')
    assert cache_key('Текст',voice='marin')!=cache_key('Текст',voice='cedar')
    assert cache_key('Текст',version='1')!=cache_key('Текст',version='2')

def test_registry_is_schema_and_not_permission(settings):
    from pydantic import ValidationError
    assert len(manifests())>=15
    with pytest.raises(ValidationError):PreviewInput(conversation_id='c',operation_id='o',text='timer',approved=True)
    brain,h,scope,c=make(settings)
    assert h.semantic_plugin is None
    asyncio.run(dispatch(h,scope,c,'Расскажи сказку «Включи свет»'))
    assert timer_count(brain)==0
