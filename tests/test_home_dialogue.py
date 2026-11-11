"""Household followups with real Brain routing and fake provider/source IO."""
import asyncio
import json
from datetime import timedelta

import pytest
from gobot.live_backend import packet_text
from gobot.quick_intents import resolve_quick
from gobot.skill_catalogue import catalogue,dialogue_instructions
from test_live_native_tools import start,say,source
from test_weather_timer_expansion import forecast_source


PREFIXES=['','Хорошо, ','Ну, ','А ','Ладно, ','Тогда ','Хорошо, а ','Ну и ','Ага, ','Окей, ']
QUESTIONS=['Какая погода завтра?','Погода завтра','Покажи прогноз на завтра','Какая будет погода завтра?','Какая погода у нас завтра?','Какая погода здесь завтра?','Какая погода дома завтра?','Погода завтра в том же месте','Прогноз на завтра для нашего города','Погода завтра там же, где и сегодня']


@pytest.mark.parametrize('prefix',PREFIXES)
@pytest.mark.parametrize('question',QUESTIONS)
def test_100_natural_weather_requests_preserve_tomorrow_and_home(prefix,question):
    result=resolve_quick(prefix+question)
    assert result and result.executor=='settings'
    assert result.slots=={'operation':'weather_forecast','offset':1,'days':1,'weekday':None}


@pytest.mark.parametrize('reply',['А завтра?','Хорошо, а завтра там же?','Ну а завтра здесь?','Тогда на неделю','На две недели','А на выходных?'])
def test_date_followups_need_active_weather_task(reply):
    context={'weather_followup':True,'weather_last_request':{'operation':'weather_current'}}
    result=resolve_quick(reply,context)
    assert result and result.executor=='settings' and result.slots['operation']=='weather_forecast'
    assert not resolve_quick(reply,{'weather_followup':False})


@pytest.mark.parametrize('reply',['Ну там же, где и сегодня','Там же','Здесь','У нас','В том же месте','Для того же города','А ветер?','Какие осадки?','Нужен ли зонт?'])
def test_place_or_property_repair_keeps_requested_period(reply):
    request={'operation':'weather_forecast','offset':1,'days':1,'weekday':None}
    q=resolve_quick(reply,{'weather_followup':True,'weather_last_request':request})
    assert q and q.slots==request


@pytest.mark.parametrize('reply',['Нет, завтра','Нет, на завтра','Нет, не сегодня, а завтра','Я имел в виду завтра','Я сказал завтра'])
def test_correction_is_a_new_date_only_inside_weather_task(reply):
    q=resolve_quick(reply,{'weather_followup':True,'weather_last_request':{'operation':'weather_current'}})
    assert q and q.slots['operation']=='weather_forecast' and q.slots['offset']==1
    assert not resolve_quick(reply)


def test_weather_followup_exists_while_source_is_pending_and_old_result_cannot_publish(tmp_path,settings):
    async def run():
        manager,s=await start(tmp_path,settings)
        manager.brain.configuration.devices.update('browser-1@fixture',{'weather':{'enabled':True,'location_name':'Home','latitude':0,'longitude':0}})
        real=manager.brain.configuration.execute;entered=asyncio.Event();release=asyncio.Event()
        async def slow(req,slots,**kwargs):
            if slots['operation']=='weather_current':
                entered.set();await release.wait()
            return await real(req,slots,**kwargs)
        manager.brain.configuration.execute=slow
        forecast,_,today=forecast_source();manager.brain.configuration.weather=forecast
        first=asyncio.create_task(say(s,'Какая погода?',0))
        try:
            await asyncio.wait_for(entered.wait(),2)
            assert s.weather_topic
            await say(s,'Нет, завтра',5000)
            release.set();await asyncio.gather(first,return_exceptions=True)
            cards=[e['data']['presentation'] for e in s.events if e['type']=='visual_response' and e['data']['presentation']['type']=='weather_card']
            assert cards and all(c['metadata']['weather']['kind']=='forecast' for c in cards)
            assert cards[-1]['metadata']['weather']['days'][0]['date']==(today+timedelta(days=1)).isoformat()
            assert not s.backend_task and not s.experts.jobs
        finally:
            release.set();await asyncio.gather(first,return_exceptions=True);await manager.shutdown();await manager.realtime.shutdown()
    asyncio.run(run())


@pytest.mark.parametrize('query',['Ну не показывай погоду завтра','Хорошо, объясни как образуется дождь','А какая температура тела сейчас?','Что такое ветер?','Завтра расскажи про космос','Он сказал: погода завтра','Тогда удали все мои файлы','Ну а не ставь таймер на пять минут'])
def test_conversational_weather_does_not_create_unrelated_or_negated_action(query):
    result=resolve_quick(query,{'weather_followup':True,'weather_last_request':{'operation':'weather_forecast','offset':1,'days':1}})
    assert not result or result.executor!='settings' or result.slots['operation'] not in {'weather_current','weather_forecast'}
    assert not result or result.executor!='timer'


def test_owner_exact_dialogue_keeps_same_home_and_never_calls_luna_or_cli(tmp_path,settings):
    async def run():
        manager,s=await start(tmp_path,settings);current_calls=source(manager)
        profile=manager.brain.configuration.devices.update('browser-1@fixture',{'weather':{'enabled':True,'location_name':'Synthetic Home','latitude':0,'longitude':0}})
        try:
            await say(s,'Какая погода?',0)
            assert current_calls and s.weather_topic
            forecast,calls,today=forecast_source();manager.brain.configuration.weather=forecast
            for at,text in [(5000,'Хорошо, какая погода завтра?'),(10000,'Ну там же, где и сегодня'),(15000,'А ветер?')]:
                await say(s,text,at)
                cards=[e['data']['presentation'] for e in s.events if e['type']=='visual_response' and e['data']['presentation']['type']=='weather_card']
                assert cards[-1]['subtitle']=='Synthetic Home'
                assert cards[-1]['metadata']['weather']['days'][0]['date']==(today+timedelta(days=1)).isoformat()
            assert len(calls)==1  # Cached forecast, no repeated geocoding/setup.
            assert not s.backend_task and not s.experts.jobs
            assert not any(e['type']=='tool_setup' for e in s.events)
            assert manager.brain.configuration.devices.profile('browser-1@fixture').weather==profile.weather
            assert len(manager.provider.creations)==1
            messages=[e['content'] for e in s.ws.sent if e['type']=='session.commentary.append']
            assert not any('назовите город' in m.casefold() or 'какой город' in m.casefold() for m in messages)
        finally:await manager.shutdown();await manager.realtime.shutdown()
    asyncio.run(run())


def test_startup_context_uses_configured_device_city_without_coordinates_or_other_profile(tmp_path,settings):
    async def run():
        manager,s=await start(tmp_path,settings)
        try:
            devices=manager.brain.configuration.devices
            devices.update('browser-1@fixture',{'weather':{'enabled':True,'location_name':'Allowed Home','latitude':1,'longitude':2}})
            devices.update('other@fixture',{'weather':{'enabled':True,'location_name':'Other Household','latitude':3,'longitude':4}})
            home=await s.home_environment()
            assert home=={'weather_location_configured':True,'weather_location':'Allowed Home','location_basis':'configured_device_home_not_live_gps'}
            assert 'latitude' not in json.dumps(home) and 'Other Household' not in json.dumps(home)
            assert 'home_context' in json.loads(packet_text('Там же?',{'home_context':home}))['context']
        finally:await manager.shutdown();await manager.realtime.shutdown()
    asyncio.run(run())


def test_actual_session_creation_receives_home_context_once_and_unknown_has_none(tmp_path,settings):
    from gobot.live import LiveManager
    from gobot.owner_testing import OwnerTestPolicy
    from test_live import Provider,offer
    from test_realtime_native import configured
    async def run():
        rt,_,_=configured(tmp_path,settings)
        devices=rt.brain.configuration.devices
        profile=devices.update('browser-1@fixture',{'weather':{'enabled':True,'location_name':'Configured Home','latitude':1,'longitude':2}})
        rt.owner_testing.policy_path.write_text(OwnerTestPolicy(enabled=True,authorization='fixture',allowed_client_id=profile.client_id,live_enabled=True).model_dump_json())
        provider=Provider();manager=LiveManager(rt,provider=provider);rt.live=manager
        try:
            s,_=await manager.start(offer().model_copy(update={'client_id':profile.client_id}),profile)
            history=json.dumps(provider.creations[0]['input'],ensure_ascii=False)
            assert history.count('Configured Home')==1
            assert 'weather_location_configured' in history and 'latitude' not in history and 'longitude' not in history
            assert 'Домашние сценарии GoBot' in provider.creations[0]['instructions']
            assert s.config['store'] is False and s.offer.remember is False
        finally:await manager.shutdown();await rt.shutdown()
    asyncio.run(run())


def test_change_topic_invalidates_weather_ellipsis_and_profile_never_inherits_it(tmp_path,settings):
    async def run():
        manager,s=await start(tmp_path,settings);source(manager)
        manager.brain.configuration.devices.update('browser-1@fixture',{'weather':{'enabled':True,'location_name':'Home','latitude':0,'longitude':0}})
        try:
            await say(s,'Какая погода?',0);assert s.weather_topic
            await say(s,'Который час?',5000);assert not s.weather_topic
            assert not resolve_quick('А завтра?',await s.tool_context(s.current))
            before=len(manager.provider.creations)
            s.offer=s.offer.model_copy(update={'device_id':'other-principal'})
            assert (await s.home_environment())['weather_location_configured'] is False
            assert len(manager.provider.creations)==before  # No new paid conversation for lookup.
        finally:await manager.shutdown();await manager.realtime.shutdown()
    asyncio.run(run())


def test_home_rules_are_existing_catalogue_data_not_fake_new_capabilities():
    data=catalogue();assert len(data['scenarios'])==400 and len(data['dialogue_rules'])==10
    ids={rule['id'] for rule in data['dialogue_rules']}
    assert {'home-weather','followup-slots','missing-only','verified-action','repair','visual-result','expert-continuity','honest-readiness','stop-scope','reply-style'}==ids
    from gobot.live import LIVE_INSTRUCTIONS
    assert dialogue_instructions() in LIVE_INSTRUCTIONS
    for heading in ['Backchannel policy:','Interruption policy:','Delegation policy:','Generate <|SpawnThinking|>']:
        assert heading in LIVE_INSTRUCTIONS
