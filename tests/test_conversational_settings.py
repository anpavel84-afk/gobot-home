"""Regression for the preserved voice-settings work; all sources are fixtures."""
import asyncio,time
import httpx,pytest
from gobot.memory import Memory
from gobot.models import ChatRequest
from gobot.device_store import DeviceStore
from gobot.settings_tools import SettingsTools,settings_intent
from gobot.weather import WeatherClient,WeatherError

def test_weather_find_confirm_readback_and_profile_isolation(tmp_path,settings):
    async def run():
        memory=Memory(settings.db);store=DeviceStore(tmp_path/'devices');p=store.profile('owner@peer');other=store.profile('other@peer')
        tools=SettingsTools(memory,tmp_path/'devices')
        class Weather:
            async def locations(self,q):return [{'location_name':'Synthetic Town','latitude':-28.0,'longitude':-48.0}]
            async def current(self,place):return {'temperature':20,'apparent':19,'wind_kmh':5,'weather_code':0,'observed_at':time.time(),'fetched_at':time.time()}
        tools.weather=Weather()
        req=ChatRequest(text='Настрой погоду для Synthetic Town',device_id='owner',client_id=p.client_id,conversation_id='conv',remember=False,profile_epoch='epoch')
        result=await tools.execute(req,{'operation':'weather_find','query':'Synthetic Town'})
        assert 'Нашёл' in result.text and not store.profile('owner@peer').weather.enabled
        pending=memory.context(req)
        intent=settings_intent('установи это основной точкой',pending)
        assert intent['operation']=='weather_confirm'
        saved=await tools.execute(req,intent)
        assert saved.profile['weather']['enabled'] and store.profile('owner@peer').weather.location_name=='Synthetic Town'
        assert not store.profile('other@peer').weather.enabled
        weather=await tools.execute(req,{'operation':'weather_current'})
        assert weather.frame.type=='weather_card' and weather.evidence['verified']
        with memory.connect() as c:assert c.execute('SELECT count(*) FROM messages').fetchone()[0]==0
    asyncio.run(run())

@pytest.mark.parametrize('patch',[{'voice':{'engine':'realtime'}},{'screen':{'generation_consent':True}},{'weather':{'latitude':12,'longitude':13,'enabled':True,'location_name':'unconfirmed'}},{'shell':{'command':'anything'}}])
def test_voice_setting_cannot_grant_permissions_or_bypass_weather_confirmation(tmp_path,settings,patch):
    async def run():
        memory=Memory(settings.db);store=DeviceStore(tmp_path/'devices');p=store.profile('owner@peer');tools=SettingsTools(memory,tmp_path/'devices')
        req=ChatRequest(text='synthetic',device_id='owner',client_id=p.client_id,remember=False)
        result=await tools.execute(req,{'operation':'patch','patch':patch})
        assert result.profile is None and store.profile('owner@peer')==p
    asyncio.run(run())

def test_weather_cache_and_stale_source_are_free_mock_checks():
    async def run():
        calls=[];clock=[10000]
        async def handler(req):
            calls.append(req)
            return httpx.Response(200,json={'current':{'time':10000,'temperature_2m':21,'apparent_temperature':20,'wind_speed_10m':4,'weather_code':0}})
        client=WeatherClient(transport=httpx.MockTransport(handler),clock=lambda:clock[0])
        from gobot.device_contract import WeatherPreferences
        place=WeatherPreferences(enabled=True,location_name='Synthetic',latitude=0,longitude=0)
        assert (await client.current(place))['temperature']==21
        await client.current(place);assert len(calls)==1
        clock[0]=20000
        with pytest.raises(WeatherError):await client.current(place)
    asyncio.run(run())
