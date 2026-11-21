"""Wake-address weather parsing; no provider, microphone or deployment calls."""
import asyncio
import json
import time

import httpx
import pytest

from gobot.memory import Memory
from gobot.models import ChatRequest
from gobot.quick_intents import normalize, resolve_quick
from gobot.settings_tools import SettingsTools
from gobot.weather import WeatherClient


@pytest.mark.parametrize('query,plain',[
    ('София, какая погода завтра?', 'Какая погода завтра?'),
    ('София какая погода?', 'Какая погода?'),
    ('София. Какая погода сегодня?', 'Какая погода сегодня?'),
    ('СОФИЯ! Какая погода сейчас?', 'Какая погода сейчас?'),
    ('София, скажи пожалуйста, какая погода завтра?', 'Какая погода завтра?'),
    ('Пожалуйста, София, покажи погоду в Москве завтра.', 'Покажи погоду в Москве завтра.'),
    ('София, какой ветер завтра в метрах в секунду?', 'Какой ветер завтра в метрах в секунду?'),
    ('София, погода на следующей неделе?', 'Погода на следующей неделе?'),
    ('София, погода через месяц?', 'Погода через месяц?'),
    ('София, покажи погоду в weather.com', 'Покажи погоду в weather.com'),
])
def test_address_preserves_validated_weather_operation_and_slots(query,plain):
    actual=resolve_quick(query)
    expected=resolve_quick(plain)
    assert actual is not None and expected is not None
    assert actual==expected
    assert actual.executor=='settings'
    assert actual.slots['operation'] in {
        'weather_current','weather_forecast','weather_unsupported','weather_provider_unavailable'}


def test_followup_keeps_selected_date_and_temporary_place_without_new_home():
    context={'weather_followup':True,'weather_last_request':{
        'operation':'weather_forecast','days':1,'start_date':'2026-11-21',
        'end_date':'2026-11-21','place_ref':'fixture-temporary-place',
        'place_label':'Fixture Place','timezone':'Europe/Lisbon'}}
    actual=resolve_quick('София, а ветер?',context)
    assert actual==resolve_quick('А ветер?',context)
    assert actual.slots['metric']=='wind'
    assert actual.slots['place_ref']=='fixture-temporary-place'
    assert actual.slots['start_date']=='2026-11-21'
    assert resolve_quick('София, а завтра?',{}) is None


@pytest.mark.parametrize('query',[
    'София', 'София.',
    'София, не надо показывать погоду',
    'София, переведи на английский: «покажи погоду завтра»',
    'София, он сказал «какая погода завтра»',
    'София, как образуется дождь?',
    'София, какая температура тела сейчас?',
    'София, выключи погоду',
    'София, удали место для погоды',
    'София, настрой погоду для Москвы',
    'София, поставь таймер на 5 минут',
    'София, отмени все таймеры',
    'София, выключи микрофон',
    'София, дай себе полный доступ',
    'Софияна, какая погода завтра?',
    'Он спросил Софию, какая погода завтра?',
])
def test_address_does_not_enable_writes_quotes_or_unrelated_requests(query):
    result=resolve_quick(query)
    assert result is None or result.executor not in {'settings','timer'}


def test_address_does_not_confirm_pending_city_change_or_timer_cancel():
    pending={'pending_action':{'id':'fixture','kind':'weather_confirm',
        'expires':time.time()+30,'payload':{'places':[{'location_name':'Fixture'}]}}}
    assert resolve_quick('София, да',pending) is None
    assert resolve_quick('Да',pending).slots['operation']=='weather_confirm'
    assert resolve_quick('София, отмени первый',{'timer_followup':True}) is None
    assert resolve_quick('Отмени первый',{'timer_followup':True}).executor=='timer'
    # The new address is deliberately not stripped by the shared command path.
    assert normalize('София, выключи погоду')=='софия, выключи погоду'


def test_addressed_weather_reads_existing_profile_and_observes_later_saved_city(tmp_path,settings):
    """Use the actual executor/SQLite profile with fake source HTTP only.

    This also checks the admin consumer boundary: each weather tool invocation
    rereads saved home; no new profile/session is needed for the source lookup.
    """
    async def run():
        tools=SettingsTools(Memory(settings.db),tmp_path/'devices')
        original=tools.devices.profile('fixture-owner@spotpear')
        first={'enabled':True,'location_name':'Fixture One','latitude':1.0,'longitude':2.0}
        saved=tools.devices.update('fixture-owner@spotpear',{'weather':first})
        req=ChatRequest(text='София, какая погода сейчас?',device_id='fixture-owner',
            client_id=original.client_id,conversation_id='weather-address-test',
            profile_epoch='fixture-epoch',remember=False)
        now=time.time();requests=[]
        def handler(request):
            requests.append(request)
            assert request.url.host=='api.open-meteo.com'
            return httpx.Response(200,json={'timezone':'UTC','current':{
                'time':now-30,'temperature_2m':22,'apparent_temperature':23,
                'weather_code':2,'wind_speed_10m':18}})
        tools.weather=WeatherClient(transport=httpx.MockTransport(handler),clock=lambda:now)
        intent=resolve_quick(req.text)
        result=await tools.execute(req,intent.slots)
        assert result.evidence['verified'] is True and result.frame.subtitle=='Fixture One'
        assert result.profile is None and result.setup is None
        assert tools.devices.profile('fixture-owner@spotpear')==saved
        assert len(requests)==1 and float(requests[0].url.params['latitude'])==1.0
        assert 'latitude' not in json.dumps(result.evidence)
        assert 'longitude' not in json.dumps(result.evidence)

        changed=tools.devices.update('fixture-owner@spotpear',{'weather':{
            **first,'location_name':'Fixture Two','latitude':3.0,'longitude':4.0}})
        updated=await tools.execute(req,intent.slots)
        assert updated.evidence['verified'] is True and updated.frame.subtitle=='Fixture Two'
        assert len(requests)==2 and float(requests[1].url.params['latitude'])==3.0
        assert tools.devices.profile('fixture-owner@spotpear')==changed
        assert updated.profile is None and updated.setup is None
    asyncio.run(run())
