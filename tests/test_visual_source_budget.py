"""Source limits and native image grants; no model or external HTTP calls."""
import asyncio
import pytest
from gobot.visual_images import ImageCache
from gobot.device_contract import DeviceProfile,ScreenPreferences
from test_realtime_native import configured,start

def test_wikimedia_budget_is_shared_without_resetting_existing_usage(tmp_path):
    clock=[100000];policy={}
    cache=ImageCache(tmp_path,clock=lambda:clock[0],request_policy_loader=lambda:policy)
    for _ in range(8):assert cache.reserve_request('ru.wikipedia.org')
    assert not cache.reserve_request('ru.wikipedia.org')
    revision=cache.request_policy_revision()
    policy['wikimedia']={'requests_per_minute':12,'requests_per_day':30}
    assert cache.request_policy_revision()!=revision
    for _ in range(4):assert cache.reserve_request('en.wikipedia.org')
    assert not cache.reserve_request('commons.wikimedia.org')
    clock[0]+=61
    assert cache.reserve_request('commons.wikimedia.org')
    with cache.connect() as c:assert c.execute('SELECT count(*) FROM source_requests').fetchone()[0]==13
    cache.delay_source('commons.wikimedia.org',3600)
    policy['wikimedia']={'requests_per_minute':60,'requests_per_day':2000}
    assert not cache.reserve_request('commons.wikimedia.org') # Never bypass remote Retry-After.
    for _ in range(8):assert cache.reserve_request('api.openverse.org')
    assert not cache.reserve_request('api.openverse.org') # Other providers unchanged.

@pytest.mark.parametrize('invalid',[{'requests_per_minute':0,'requests_per_day':2000},{'requests_per_minute':10000,'requests_per_day':10000},{'requests_per_minute':True,'requests_per_day':2000},None])
def test_malformed_or_unbounded_source_policy_keeps_conservative_defaults(tmp_path,invalid):
    cache=ImageCache(tmp_path,request_policy_loader=lambda:{'wikimedia':invalid})
    assert cache.request_limits('ru.wikipedia.org')['requests_per_minute']==8

@pytest.mark.parametrize('cap',[0,5,20])
def test_native_server_grant_caps_profile_generation_limit(tmp_path,settings,cap):
    async def run():
        manager,provider,budget=configured(tmp_path,settings)
        budget.policy_path.write_text(budget.policy().model_copy(update={'image_generation_allowed':True,'image_generation_daily_limit':cap}).model_dump_json(),encoding='utf-8')
        async def profile(_):return DeviceProfile(screen=ScreenPreferences(generation_allowed=True,generation_consent=True,generation_mode='missing',generation_daily_limit=20,generation_provider='openai'))
        manager.profile_loader=profile
        session=await start(manager)
        try:assert session.profile.screen.generation_daily_limit==cap
        finally:await manager.shutdown()
    asyncio.run(run())

@pytest.mark.parametrize('query',[
    'Сколько волос у человека на голове?',
    'Сколько у человека волос на голове?',
    'Сколько волос на голове человека?',
])
def test_quantified_subject_is_hair_not_its_possessor(query):
    from gobot.visual_prefetch import extract_entity
    assert extract_entity(query).query=='волосы'

def test_negative_source_cache_is_revisited_after_budget_policy_change(tmp_path):
    from gobot.visual import VisualService
    from gobot.presentation import VisualIntent
    from gobot.models import ChatRequest
    from test_visual_source_policy import Provider,candidate
    async def run():
        policy={};cache=ImageCache(tmp_path,request_policy_loader=lambda:policy)
        events=[];provider=Provider('wiki',events)
        visual=VisualService(cache,provider_factory=lambda _:provider,config_loader=lambda:{'provider':'wikimedia','contact':'https://example.org','user_agent':'fixture'})
        req=ChatRequest(text='Покажи орла',mode='auto')
        one=await visual.images(req,VisualIntent('image',query='eagle'))
        assert not one.frame.images
        provider.items=[candidate('eagle')]
        policy['wikimedia']={'requests_per_minute':60,'requests_per_day':2000}
        two=await visual.images(req,VisualIntent('image',query='eagle'))
        assert two.frame.images
    asyncio.run(run())

def test_followup_silence_closes_mic_without_cancelling_approved_image_worker(tmp_path,settings):
    import time
    from test_two_stage_visual import result
    async def run():
        manager,provider,budget=configured(tmp_path,settings);gate=asyncio.Event();entered=asyncio.Event()
        budget.policy_path.write_text(budget.policy().model_copy(update={'image_generation_allowed':True,'image_generation_daily_limit':1}).model_dump_json(),encoding='utf-8')
        async def profile(_):return DeviceProfile(screen=ScreenPreferences(generation_allowed=True,generation_consent=True,generation_mode='missing',generation_daily_limit=1,generation_provider='openai'))
        async def fetch(req,plan,**kw):
            if req.screen_preferences.generation_allowed:entered.set();await gate.wait();return result(plan.visual_query)
            return result(plan.visual_query,missing=True)
        manager.profile_loader=profile;manager.brain.visual.attachment=fetch;session=await start(manager)
        try:
            turn=await session.new_turn(query='Покажи орла');await asyncio.wait_for(entered.wait(),1)
            session.followup_deadline=time.monotonic()-1;session.last_activity=time.monotonic()-100
            for _ in range(80):
                if session.input_mode=='waiting_visual':break
                await asyncio.sleep(.02)
            assert not session.closed and session.input_mode=='waiting_visual'
            assert next(e for e in session.events if e['type']=='followup_closed')['data']['microphone'] is False
            gate.set();await asyncio.wait_for(turn.visual_ready.wait(),1)
            assert turn.visual_outcome['asset_delivered']
        finally:gate.set();await manager.shutdown()
    asyncio.run(run())
