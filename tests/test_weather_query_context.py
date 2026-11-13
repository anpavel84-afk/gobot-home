"""Read-only weather dialogue regression: real parser, store and source validation, fake HTTP only."""
import asyncio
import json
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest

from gobot.memory import Memory
from gobot.models import ChatRequest
from gobot.settings_tools import SettingsTools,settings_intent
from gobot.weather import WeatherClient,WeatherError
from gobot.weather_queries import weather_query,weather_followup,weather_request_context
from gobot.device_contract import WeatherPreferences

NOW=datetime(2026,11,11,23,tzinfo=ZoneInfo('UTC')).timestamp()
HOME={'enabled':True,'location_name':'Fixture Home, Sao Paulo','latitude':-23.55,'longitude':-46.63}


def payload(zone,now,*,optional=True):
    today=datetime.fromtimestamp(now,ZoneInfo(zone)).date()
    daily={'time':[(today+timedelta(days=i)).isoformat() for i in range(16)],
        'weather_code':[2]*16,'temperature_2m_min':[18+i%3 for i in range(16)],
        'temperature_2m_max':[25+i%3 for i in range(16)],
        'precipitation_probability_max':[20+i*3 for i in range(16)],'wind_speed_10m_max':[18+i for i in range(16)]}
    current={'time':now-30,'temperature_2m':22,'apparent_temperature':23,'weather_code':2,'wind_speed_10m':18}
    if optional:
        daily.update({'wind_gusts_10m_max':[27+i for i in range(16)],'precipitation_sum':[round(i*.7,1) for i in range(16)],'uv_index_max':[4]*16})
        current.update({'wind_gusts_10m':27,'relative_humidity_2m':65,'precipitation':0})
    return {'timezone':zone,'current':current,'daily':daily}


def configured(tmp_path,settings,*,home=True,remember=False,optional=True,error=None):
    memory=Memory(settings.db);tools=SettingsTools(memory,tmp_path/'devices')
    profile=tools.devices.profile('owner@fixture')
    if home:profile=tools.devices.update('owner@fixture',{'weather':HOME})
    req=ChatRequest(text='fixture',device_id='owner',client_id=profile.client_id,conversation_id='weather-conversation',profile_epoch='epoch-1',remember=remember)
    calls=[];clock=[NOW]
    def handle(request):
        calls.append(request)
        if 'geocoding-api' in request.url.host:
            name=request.url.params['name'].casefold()
            if name in {'москва','москве'}:results=[{'name':'Москва','admin1':'Москва','country':'Россия','latitude':55.75,'longitude':37.62,'timezone':'Europe/Moscow'}]
            elif name in {'лиссабон','лиссабоне'}:results=[{'name':'Лиссабон','country':'Португалия','latitude':38.72,'longitude':-9.14,'timezone':'Europe/Lisbon'}]
            elif name in {'рио','рио-де-жанейро'}:results=[{'name':'Рио-де-Жанейро','country':'Бразилия','latitude':-22.91,'longitude':-43.17,'timezone':'America/Sao_Paulo'}]
            elif name in {'спрингфилд','спрингфилде'}:results=[
                {'name':'Спрингфилд','admin1':'Иллинойс','country':'США','latitude':39.8,'longitude':-89.64,'timezone':'America/Chicago'},
                {'name':'Спрингфилд','admin1':'Массачусетс','country':'США','latitude':42.1,'longitude':-72.59,'timezone':'America/New_York'}]
            else:results=[]
            return httpx.Response(200,json={'results':results})
        if error=='timeout':raise httpx.ReadTimeout('synthetic timeout',request=request)
        if isinstance(error,int):return httpx.Response(error,json={'error':True})
        lat=float(request.url.params['latitude'])
        zone='Europe/Moscow' if lat==55.75 else 'Europe/Lisbon' if lat==38.72 else 'America/Chicago' if lat==39.8 else 'America/New_York' if lat==42.1 else 'America/Sao_Paulo'
        return httpx.Response(200,json=payload(zone,clock[0],optional=optional))
    tools.weather=WeatherClient(transport=httpx.MockTransport(handle),clock=lambda:clock[0])
    return tools,req,profile,calls,clock


def context(result):
    return {'weather_followup':True,'weather_last_request':result.evidence['weather_request']}


def test_temporary_city_uses_its_calendar_and_metric_followup_reuses_resolved_place(tmp_path,settings):
    async def run():
        tools,req,home,calls,_=configured(tmp_path,settings)
        result=await tools.execute(req,weather_query('Какая завтра погода в Москве?'))
        assert result.evidence['verified'] and result.setup is None and result.profile is None
        assert result.evidence['weather_request']['timezone']=='Europe/Moscow'
        assert result.evidence['weather_request']['start_date']=='2026-11-13'
        assert result.frame.metadata.weather.days[0].date=='2026-11-13'
        assert result.frame.metadata.weather.place=='Москва, Россия'
        wind=await tools.execute(req,weather_followup('А ветер?',context(result)))
        assert wind.frame.metadata.weather.metric=='wind'
        assert wind.frame.metadata.weather.days[0].gust_kmh==28
        assert 'ветер до 19 км/ч' in wind.text and 'Порывы до 28 км/ч' in wind.text
        assert 'температур' not in wind.text and 'вероятность' not in wind.text
        assert wind.evidence['weather_request']['start_date']=='2026-11-13'
        assert len(calls)==2 and sum('geocoding-api' in r.url.host for r in calls)==1
        assert tools.devices.profile('owner@fixture')==home
        assert 'latitude' not in json.dumps(wind.evidence) and 'longitude' not in json.dumps(wind.evidence)
        back=await tools.execute(req,weather_followup('А дома завтра?',context(wind)))
        assert back.evidence['weather_request']['start_date']=='2026-11-12'
        assert back.evidence['weather_request']['timezone']=='America/Sao_Paulo'
        assert 'place_ref' not in back.evidence['weather_request']
        assert back.frame.subtitle==HOME['location_name'] and len(calls)==3
    asyncio.run(run())


def test_missing_home_asks_once_and_reply_only_resolves_ephemeral_place(tmp_path,settings):
    async def run():
        tools,req,profile,calls,_=configured(tmp_path,settings,home=False,remember=True)
        result=await tools.execute(req,weather_query('Погода завтра'))
        assert result.text=='Для какого города показать погоду?' and result.setup is None and not calls
        query_context=tools.weather_query_context(req)
        pending=query_context['weather_query_pending']
        assert pending['kind']=='weather_query_location' and pending['payload']['request']['offset']==1
        assert tools.memory.context(req).get('pending_action') is None
        slots=settings_intent('лиссабон',query_context)
        assert slots['operation']=='weather_query_find'
        found=await tools.execute(req,slots)
        assert found.evidence['weather_request']['start_date']=='2026-11-12'
        assert found.frame.subtitle=='Лиссабон, Португалия'
        assert found.frame.metadata.weather.timezone=='Europe/Lisbon'
        assert tools.devices.profile('owner@fixture')==profile
        assert tools.weather_query_context(req)=={}
        with tools.memory.connect() as connection:
            assert connection.execute('SELECT count(*) FROM messages').fetchone()[0]==0
    asyncio.run(run())


def test_region_choice_uses_pending_candidates_without_source_or_home_reconfiguration(tmp_path,settings):
    async def run():
        tools,req,profile,calls,_=configured(tmp_path,settings)
        ambiguous=await tools.execute(req,weather_query('Погода в Спрингфилде'))
        assert ambiguous.evidence['reason']=='weather_location_ambiguous' and len(calls)==1
        public=tools.weather_query_context(req)
        assert 'latitude' not in json.dumps(public) and 'longitude' not in json.dumps(public)
        assert public['weather_query_pending']['payload']['places'][1]['location_name']=='Спрингфилд, Массачусетс, США'
        chosen=await tools.execute(req,settings_intent('в иллинойсе',public))
        assert chosen.frame.subtitle=='Спрингфилд, Иллинойс, США'
        assert chosen.evidence['weather_request']['timezone']=='America/Chicago'
        assert len(calls)==2 and tools.devices.profile('owner@fixture')==profile
    asyncio.run(run())


@pytest.mark.parametrize('scope_change',[{'conversation_id':'other-conversation'},{'profile_epoch':'epoch-2'}])
def test_temporary_ref_and_pending_are_isolated_by_conversation_and_epoch(tmp_path,settings,scope_change):
    async def run():
        tools,req,_,calls,_=configured(tmp_path,settings)
        original=await tools.execute(req,weather_query('Погода в Рио'))
        other=req.model_copy(update=scope_change)
        assert tools.weather_query_context(other)=={}
        rejected=await tools.execute(other,weather_followup('А завтра?',context(original)))
        assert rejected.evidence['reason']=='weather_place_expired' and len(calls)==2
        assert rejected.frame is None
        assert tools.weather_query_context(req)=={}
        again=await tools.execute(req,weather_followup('А завтра?',context(original)))
        assert again.frame.subtitle.startswith('Рио-де-Жанейро') and len(calls)==3
    asyncio.run(run())


def test_pending_city_isolated_across_device_and_client_and_expires(tmp_path,settings):
    async def run():
        tools,req,profile,calls,_=configured(tmp_path,settings,home=False)
        await tools.execute(req,weather_query('Погода завтра'))
        public=tools.weather_query_context(req)
        for changes in ({'client_id':'other-client'},{'device_id':'other-owner'},{'profile_epoch':'other-epoch'},{'conversation_id':'other-conversation'}):
            assert tools.weather_query_context(req.model_copy(update=changes))=={}
        # Mutation of the returned compact context cannot change server candidates or request.
        public['weather_query_pending']['payload']['request']['offset']=15
        assert tools.weather_query_context(req)['weather_query_pending']['payload']['request']['offset']==1
        expired=tools.weather_query_context(req)['weather_query_pending']
        tools._weather_queries[tools._weather_scope(req)]['expires']=0
        assert tools.weather_query_context(req)=={}
        result=await tools.execute(req,{'operation':'weather_query_find','query':'Лиссабон','pending_id':expired['id']})
        assert result.evidence['reason']=='weather_query_expired' and not calls
        assert tools.devices.profile('owner@fixture')==profile
    asyncio.run(run())


@pytest.mark.parametrize('decline',['нет спасибо','не надо показывать погоду'])
def test_decline_cancels_only_read_only_pending_and_keeps_home(tmp_path,settings,decline):
    async def run():
        tools,req,profile,calls,_=configured(tmp_path,settings)
        await tools.execute(req,weather_query('Погода в Спрингфилде'))
        result=await tools.execute(req,settings_intent(decline,tools.weather_query_context(req)))
        assert result.evidence['reason']=='weather_query_cancelled'
        assert tools.weather_query_context(req)=={} and len(calls)==1
        assert tools.devices.profile('owner@fixture')==profile
    asyncio.run(run())


@pytest.mark.parametrize('error,reason',[('timeout','weather_source_timeout'),(503,'weather_source_unavailable'),(429,'weather_provider_rate_limit')])
def test_failures_preserve_reason_and_do_not_retry_or_reconfigure(tmp_path,settings,error,reason):
    async def run():
        tools,req,profile,calls,_=configured(tmp_path,settings,error=error)
        result=await tools.execute(req,weather_query('Погода завтра'))
        assert result.evidence['reason']==reason and not result.evidence['verified']
        assert result.frame is None and result.setup is None and len(calls)==1
        assert not any(symbol in result.text for symbol in ('°','км/ч'))
        assert tools.devices.profile('owner@fixture')==profile
    asyncio.run(run())


def test_missing_optional_field_is_reported_without_inventing_gust_or_uv(tmp_path,settings):
    async def run():
        tools,req,_,_,_=configured(tmp_path,settings,optional=False)
        wind=await tools.execute(req,weather_query('Какой ветер завтра?'))
        assert 'Данных о порывах источник не вернул' in wind.text
        assert wind.frame.metadata.weather.days[0].gust_kmh is None
        uv=await tools.execute(req,{'operation':'weather_forecast','offset':1,'days':1,'metric':'uv_index'})
        assert uv.evidence['reason']=='weather_metric_unavailable'
        assert uv.frame.metadata.weather.days[0].uv_index is None
    asyncio.run(run())


def test_current_response_is_not_published_after_cancellation(tmp_path,settings):
    async def run():
        tools,req,profile,_,_=configured(tmp_path,settings)
        current=[True]
        async def handler(request):
            current[0]=False
            return httpx.Response(200,json=payload('America/Sao_Paulo',NOW))
        tools.weather=WeatherClient(transport=httpx.MockTransport(handler),clock=lambda:NOW)
        result=await tools.execute(req,{'operation':'weather_current'},is_current=lambda:current[0])
        assert result.frame is None and not (result.evidence or {}).get('verified')
        assert 'weather_request' not in (result.evidence or {})
        assert tools.devices.profile('owner@fixture')==profile
    asyncio.run(run())


@pytest.mark.parametrize('utc,zone,period,start,end',[
    ('2026-11-11T23:00:00+00:00','America/Sao_Paulo','next_week','2026-11-16','2026-11-22'),
    ('2026-11-11T23:00:00+00:00','Europe/Moscow','next_week','2026-11-16','2026-11-22'),
    ('2026-11-15T14:00:00+00:00','America/Sao_Paulo','next_weekend','2026-11-21','2026-11-22'),
    ('2026-10-31T16:00:00+00:00','America/New_York','next_week','2026-11-02','2026-11-08'),
])
def test_calendar_ranges_use_destination_zone_across_midnight_weekend_and_dst(utc,zone,period,start,end):
    async def run():
        now=datetime.fromisoformat(utc).timestamp()
        client=WeatherClient(transport=httpx.MockTransport(lambda request:httpx.Response(200,json=payload(zone,now))),clock=lambda:now)
        result=await client.forecast(WeatherPreferences(enabled=True,location_name='Fixture',latitude=1,longitude=2),days=1,calendar_period=period)
        assert result['days'][0]['date']==start and result['days'][-1]['date']==end
    asyncio.run(run())


def test_absolute_selected_day_stays_fixed_across_midnight_and_horizon_is_bounded():
    async def run():
        now=datetime(2026,11,12,3,5,tzinfo=ZoneInfo('UTC')).timestamp()
        calls=[]
        def handler(request):calls.append(request);return httpx.Response(200,json=payload('America/Sao_Paulo',now))
        client=WeatherClient(transport=httpx.MockTransport(handler),clock=lambda:now)
        place=WeatherPreferences(enabled=True,location_name='Fixture',latitude=1,longitude=2)
        result=await client.forecast(place,days=1,start_date='2026-11-12',end_date='2026-11-12')
        assert result['days'][0]['date']=='2026-11-12'
        with pytest.raises(WeatherError,match='weather_forecast_horizon'):
            await client.forecast(place,days=1,start_date='2026-12-01',end_date='2026-12-01')
        assert len(calls)==1
    asyncio.run(run())


@pytest.mark.parametrize('query',['Переведи на английский: «покажи погоду завтра»','Не надо показывать погоду','Как образуется дождь?','Какая температура тела сейчас?'])
def test_read_only_weather_does_not_execute_quoted_negated_or_explanatory_text(query):
    assert weather_query(query) is None


def test_combined_metrics_and_calendar_place_parse_without_dropping_requested_fields():
    all_fields=weather_query('Завтра температура, дождь и ветер?')
    assert all_fields=={'operation':'weather_forecast','offset':1,'days':1,'weekday':None}
    next_week=weather_query('Какая погода в Рио на следующей неделе?')
    assert next_week['place_query']=='рио' and next_week['calendar_period']=='next_week'
    assert settings_intent('смени источник погоды на weather.com')=={'operation':'weather_provider_unavailable'}
    assert weather_query('Сравни погоду завтра в Москве и Рио')['operation']=='weather_unsupported'
    safe=weather_request_context({'operation':'weather_current','place_ref':'server-ref','latitude':12,'longitude':34,'untrusted':'text'})
    assert safe=={'operation':'weather_current','place_ref':'server-ref'}


@pytest.mark.parametrize('query',['Погода 26 ноября','Погода пятнадцатого ноября','Погода 2026-11-20'])
def test_unimplemented_absolute_date_never_silently_becomes_current(query):
    assert weather_query(query)['operation']=='weather_unsupported'


def test_city_and_self_correction_holdouts_preserve_meaning():
    assert weather_query('Погода в São Paulo завтра')['place_query']=='são paulo'
    assert weather_query('Погода в Москве на 3 дня')['place_query']=='москве'
    assert weather_query('Погода завтра, нет, сегодня')['offset']==0
    assert weather_query('Погода сегодня, нет, послезавтра')['offset']==2
    followup=weather_followup('А на следующих выходных?',{'weather_followup':True,'weather_last_request':{'operation':'weather_current'}})
    assert followup['calendar_period']=='next_weekend' and followup['days']==2


def test_active_weather_decline_without_missing_city_cancels_task_not_conversation(tmp_path,settings):
    async def run():
        tools,req,profile,calls,_=configured(tmp_path,settings)
        actual=await tools.execute(req,weather_query('Погода завтра'))
        assert actual.frame and tools.weather_query_context(req)=={}
        slots=settings_intent('не надо показывать погоду',context(actual))
        assert slots=={'operation':'weather_query_cancel'}
        declined=await tools.execute(req,slots)
        assert declined.evidence['reason']=='weather_query_cancelled' and len(calls)==1
        assert declined.setup is None and tools.devices.profile('owner@fixture')==profile
        assert settings_intent('не надо показывать погоду',{}) is None
        resumed=await tools.execute(req,weather_query('Погода завтра'))
        assert resumed.evidence['verified'] and resumed.frame
    asyncio.run(run())
