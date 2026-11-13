"""Real native Brain path, fake provider/weather. No model or weather API calls."""
import asyncio,json,sqlite3
from types import SimpleNamespace
import pytest
from test_board_realtime import prepared,enable,offer
from gobot.settings_tools import device_home_context,SettingsResult
from gobot.device_contract import WeatherPreferences,DeviceProfile

def test_home_context_is_bound_and_has_no_coordinates():
    def scope(device,client):
        if (device,client)!=('board','board'):raise ValueError()
        return 'bound'
    devices=SimpleNamespace(scoped_owner=scope,profile=lambda _:SimpleNamespace(weather=WeatherPreferences(enabled=True,location_name='Fixture City',latitude=10,longitude=20)))
    data=device_home_context(devices,'board','board')
    assert data=={'weather_location_configured':True,'weather_location':'Fixture City','location_basis':'configured_device_home_not_live_gps'}
    assert device_home_context(devices,'board','phone')['weather_location_configured'] is False

@pytest.mark.parametrize('question,operation',[
    ('Какая погода завтра?','weather_forecast'),('Погода за.','weather_unsupported')])
def test_native_uses_actual_weather_transcript_not_model_invention(tmp_path,settings,question,operation):
    original,b,provider,path=prepared(tmp_path,settings);enable(path);calls=[]
    board='spotpear-000000000001'
    policy=json.loads(path.read_text());policy['allowed_client_id']=board;path.write_text(json.dumps(policy))
    devices=original.brain.configuration.devices
    profile=DeviceProfile(client_id=board,client_kind='spotpear',weather=WeatherPreferences(enabled=True,location_name='Fixture Home',latitude=10,longitude=20))
    with sqlite3.connect(devices.db) as db:db.execute('INSERT OR REPLACE INTO profiles VALUES(?,?)',(board+'@hardware',profile.model_dump_json()))
    async def execute(req,slots,**kwargs):
        calls.append((req.text,slots));return SettingsResult('Fixture weather result',evidence={'reason':'weather_ambiguous_period'} if slots['operation']=='weather_unsupported' else {'verified':True})
    original.brain.configuration.execute=execute
    async def run():
        try:
            await b.start(offer().model_copy(update={'device_id':board,'client_id':board}));s=b.sessions['board-b-1'];turn=await s.new_turn(query=question)
            instructions=provider.creations[0][1]['instructions']
            seed=json.loads(instructions.split('Контекст JSON:\n')[1].split('\n')[0])
            assert seed['home_context']['weather_location']=='Fixture Home'
            assert 'latitude' not in seed['home_context'] and 'longitude' not in seed['home_context']
            await s.tool('read-weather','gobot_tool',json.dumps({'query':'У меня нет указания города; погода недоступна, спросите город и настройте функцию.'}),turn)
            assert calls[0][0]==question and calls[0][1]['operation']==operation
            if operation=='weather_forecast':
                turn=await s.new_turn(query='А послезавтра?')
                await s.tool('read-followup','gobot_tool',json.dumps({'query':'Покажите погоду, но где находится пользователь?'}),turn)
                assert calls[-1][0]=='А послезавтра?' and calls[-1][1]['offset']==2
                await s.new_turn(query='Расскажи о Луне')
                assert not s.weather_topic and not s.weather_last_request
            else:
                turn=await s.new_turn(query='Завтра')
                await s.tool('clarify-day','gobot_tool',json.dumps({'query':'Какая погода?'}),turn)
                assert calls[-1][0]=='Завтра' and calls[-1][1]['operation']=='weather_forecast' and calls[-1][1]['offset']==1
        finally:await b.shutdown();await original.shutdown()
    asyncio.run(run())

@pytest.mark.parametrize('question',['Погода за.','Прогноз на','Погода через'])
def test_incomplete_period_needs_day_not_new_location(question):
    from gobot.weather_queries import weather_query
    assert weather_query(question)=={'operation':'weather_unsupported','reason':'ambiguous_period'}
