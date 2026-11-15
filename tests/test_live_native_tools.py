"""Actual Brain tools behind a fake Live sideband; no paid/audio calls."""
import asyncio,time,threading
import httpx
from gobot.live import LiveManager
from gobot.live_contract import LiveCommand
from gobot.owner_testing import OwnerTestPolicy
from gobot.weather import WeatherClient
from test_live import Provider,offer
from test_realtime_native import configured


async def start(tmp_path,settings):
    rt,_,_=configured(tmp_path,settings)
    profile=rt.brain.configuration.devices.profile('browser-1@fixture')
    rt.owner_testing.policy_path.write_text(OwnerTestPolicy(enabled=True,authorization='fixture',
        allowed_client_id=profile.client_id,live_enabled=True,device_settings_enabled=True).model_dump_json())
    provider=Provider();manager=LiveManager(rt,provider=provider);rt.live=manager
    session,_=await manager.start(offer().model_copy(update={'client_id':profile.client_id}),profile)
    return manager,session


async def say(session,text,at,*,ended=True,answer=None):
    await session.handle({'type':'session.input_transcript.delta','event_id':'in-'+str(at),
        'start_ms':at,'end_ms':at+1000,'delta':text})
    if answer:
        await session.handle({'type':'session.output_transcript.delta','event_id':'out-'+str(at),
            'start_ms':at+1100,'end_ms':at+1800,'delta':answer})
    if ended:
        await session.command(LiveCommand(command_id='activity-'+str(at),action='activity',input_active=False,playback_active=False))
    await session.mode_control_task


def count_timers(manager):
    with manager.brain.memory.connect() as c:return c.execute('SELECT count(*) FROM timers').fetchone()[0]


def source(manager):
    calls=[]
    def handler(request):
        calls.append(request)
        if request.url.host=='geocoding-api.open-meteo.com':
            return httpx.Response(200,json={'results':[{'name':'Synthetic Town','admin1':'Test Region','country':'Fixture','latitude':0,'longitude':0}]})
        return httpx.Response(200,json={'current':{'time':time.time(),'temperature_2m':23.5,
            'apparent_temperature':24,'wind_speed_10m':7,'weather_code':0}})
    manager.brain.configuration.weather=WeatherClient(transport=httpx.MockTransport(handler))
    return calls


def test_native_timer_without_delegation_then_late_delegation_and_intentional_repeat(tmp_path,settings):
    async def run():
        manager,s=await start(tmp_path,settings)
        try:
            # Reproduce Live's refusal: server must still fulfill a validated command.
            await say(s,'Поставь таймер на пять секунд',0,ended=False,answer='Поставьте таймер на телефоне сами.')
            assert count_timers(manager)==1
            assert any(e['type']=='visual_response' and e['data']['presentation']['type']=='timer_widget' for e in s.events)
            assert any(e['type']=='session.commentary.append' and e['delegation_id'] is None and 'таймер' in e['content'].casefold() for e in s.ws.sent)
            await s.handle({'type':'session.delegation.created','event_id':'late','offset_ms':1000,'delegation':{'id':'late-delegation','target':'client'}})
            await s.delegation_tasks['late-delegation']
            assert count_timers(manager)==1
            assert any(e['type']=='session.thinking.append' and e['delegation_id']=='late-delegation' and 'повторного исполнения нет' in e['content'] for e in s.ws.sent)
            await say(s,'Поставь таймер на пять секунд',5000)
            assert count_timers(manager)==2  # Same words, genuinely new user turn.
            assert not s.backend_task and not s.experts.jobs
            assert len(manager.provider.creations)==1
        finally:await manager.shutdown();await manager.realtime.shutdown()
    asyncio.run(run())


def test_native_timer_missing_duration_continues_in_existing_timer_scope(tmp_path,settings):
    async def run():
        manager,s=await start(tmp_path,settings)
        try:
            await say(s,'Поставь таймер',0)
            assert count_timers(manager)==0
            await say(s,'На пять минут',5000)
            assert count_timers(manager)==1
            assert not s.backend_task and not s.experts.jobs
        finally:await manager.shutdown();await manager.realtime.shutdown()
    asyncio.run(run())


def test_old_delegation_after_new_topic_cannot_restore_old_turn_or_action(tmp_path,settings):
    async def run():
        manager,s=await start(tmp_path,settings)
        try:
            await say(s,'Поставь таймер на пять секунд',0)
            await say(s,'Который час?',5000)
            current=s.current;turn_count=len(s.turns)
            await s.handle({'type':'session.delegation.created','event_id':'stale','offset_ms':1000,'delegation':{'id':'stale-delegation','target':'client'}})
            await s.delegation_tasks['stale-delegation']
            assert s.current is current and len(s.turns)==turn_count and count_timers(manager)==1
            assert any(e['type']=='session.thinking.append' and e['delegation_id']=='stale-delegation' for e in s.ws.sent)
        finally:await manager.shutdown();await manager.realtime.shutdown()
    asyncio.run(run())


def test_delegation_racing_native_execution_cannot_create_second_timer(tmp_path,settings):
    async def run():
        manager,s=await start(tmp_path,settings)
        loop=asyncio.get_running_loop();entered=asyncio.Event();release=threading.Event()
        original=manager.brain.tools.execute
        def slow(*args,**kwargs):
            loop.call_soon_threadsafe(entered.set)
            assert release.wait(3)
            return original(*args,**kwargs)
        manager.brain.tools.execute=slow
        try:
            task=asyncio.create_task(say(s,'Поставь таймер на пять секунд',0))
            await asyncio.wait_for(entered.wait(),2)
            await s.route(s.current,'racing-operation','racing-delegation')
            release.set();await task
            assert count_timers(manager)==1 and not s.experts.jobs and not s.backend_task
        finally:release.set();await manager.shutdown();await manager.realtime.shutdown()
    asyncio.run(run())


def test_native_weather_uses_existing_saved_place_source_and_card(tmp_path,settings):
    async def run():
        manager,s=await start(tmp_path,settings);calls=source(manager)
        manager.brain.configuration.devices.update('browser-1@fixture',{'weather':{
            'enabled':True,'location_name':'Synthetic Town','latitude':0,'longitude':0}})
        try:
            await say(s,'Посмотри погоду',0)
            assert len(calls)==1 and calls[0].url.host=='api.open-meteo.com'
            cards=[e['data']['presentation'] for e in s.events if e['type']=='visual_response' and e['data']['presentation']['type']=='weather_card']
            assert cards and cards[-1]['metadata']['facts']['temperature']=='23.5'
            assert any(e['type']=='session.commentary.append' and 'Open-Meteo' in e['content'] for e in s.ws.sent)
            assert any(e['type']=='local_tool_status' and e['data'].get('has_source') for e in s.events)
            assert not s.backend_task and not s.experts.jobs
        finally:await manager.shutdown();await manager.realtime.shutdown()
    asyncio.run(run())


def test_native_weather_setup_permission_location_confirmation_source_and_isolation(tmp_path,settings):
    async def run():
        manager,s=await start(tmp_path,settings);calls=source(manager)
        manager.brain.configuration.devices.profile('other@fixture')
        try:
            # An informational query is read-only. Explicit settings open the
            # existing permission/location/confirmation/save wizard.
            for i,text in enumerate(['Покажи настройки погоды','Да','Synthetic Town','Да']):
                await say(s,text,i*5000)
            saved=manager.brain.configuration.devices.profile('browser-1@fixture')
            assert saved.weather.enabled and saved.weather.location_name=='Synthetic Town, Test Region, Fixture'
            assert not manager.brain.configuration.devices.profile('other@fixture').weather.enabled
            assert len(calls)==2  # One geocode, one real adapter fetch through fake HTTP.
            states=[e['data']['setup']['status'] for e in s.events if e['type']=='tool_setup']
            assert states==['awaiting_permission','awaiting_location','awaiting_confirmation','ready']
            assert not s.backend_task and not s.experts.jobs
        finally:await manager.shutdown();await manager.realtime.shutdown()
    asyncio.run(run())


def test_native_network_gap_or_corrected_command_cannot_create_timer(tmp_path,settings):
    async def run():
        manager,s=await start(tmp_path,settings)
        try:
            await say(s,'Поставь таймер на пять секунд',0,ended=False)
            assert count_timers(manager)==0
            # A correction arriving before the settled input-end cancels old work.
            await s.handle({'type':'session.input_transcript.delta','event_id':'partial','start_ms':5000,'end_ms':5500,'delta':'Поставь таймер на пять секунд'})
            await s.handle({'type':'session.input_transcript.delta','event_id':'correction','start_ms':5500,'end_ms':6000,'delta':', нет, не ставь'})
            await s.command(LiveCommand(command_id='end-correction',action='activity',input_active=False,playback_active=False))
            await s.mode_control_task
            assert count_timers(manager)==0
        finally:await manager.shutdown();await manager.realtime.shutdown()
    asyncio.run(run())


def test_native_weather_settings_still_require_owner_permission(tmp_path,settings):
    async def run():
        manager,s=await start(tmp_path,settings);calls=source(manager)
        policy=manager.owner_testing.policy()
        manager.owner_testing.policy_path.write_text(policy.model_copy(update={'device_settings_enabled':False}).model_dump_json())
        try:
            await say(s,'Настрой погоду',0)
            assert not manager.brain.configuration.devices.profile('browser-1@fixture').weather.enabled
            assert not calls and not s.experts.jobs
            assert any(e['type']=='local_tool_status' and e['data'].get('reason')=='owner_device_permission_required' for e in s.events)
        finally:await manager.shutdown();await manager.realtime.shutdown()
    asyncio.run(run())


def test_native_setup_cancel_or_profile_close_does_not_leave_action(tmp_path,settings):
    async def run():
        manager,s=await start(tmp_path,settings);calls=source(manager)
        try:
            await say(s,'Какая погода?',0)
            await say(s,'Нет',5000)
            assert not manager.brain.configuration.devices.profile('browser-1@fixture').weather.enabled
            assert not calls and not s.experts.jobs
            await s.handle({'type':'session.input_transcript.delta','event_id':'before-profile-switch','start_ms':10000,'end_ms':11000,'delta':'Поставь таймер на пять минут'})
            task=s.mode_control_task
            await manager.invalidate_principal('browser-1')
            await asyncio.gather(task,return_exceptions=True)
            assert s.closed and count_timers(manager)==0
        finally:await manager.shutdown();await manager.realtime.shutdown()
    asyncio.run(run())


def test_local_tool_failure_clears_pending_and_never_retries_or_exposes_exception(tmp_path,settings):
    async def run():
        manager,s=await start(tmp_path,settings);calls=[]
        def broken(*args,**kwargs):calls.append(True);raise RuntimeError('synthetic-secret-must-not-leak')
        manager.brain.tools.execute=broken
        try:
            await say(s,'Поставь таймер на пять секунд',0)
            await s.route(s.current,'late-operation','late-delegation')
            assert len(calls)==1 and not s.backend_task
            assert any(e['type']=='local_tool_status' and e['data']['state']=='failed' for e in s.events)
            assert 'synthetic-secret' not in str(s.events)+str(s.ws.sent)
        finally:await manager.shutdown();await manager.realtime.shutdown()
    asyncio.run(run())
