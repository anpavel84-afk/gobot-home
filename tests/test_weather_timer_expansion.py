import asyncio,json,subprocess,time
from pathlib import Path
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
import httpx,pytest
from gobot.weather import WeatherClient,WeatherError,condition
from gobot.device_contract import WeatherPreferences
from gobot.quick_intents import resolve_quick
from gobot.local_tools import LocalTools
from gobot.memory import Memory
from gobot.models import ChatRequest
from gobot.quick_utilities import execute
from gobot.owner_testing import OwnerTestPolicy,OwnerTesting
from test_live_native_tools import start,say,count_timers

ROOT=Path(__file__).parents[1]
VERBS=['Поставь таймер на','Засеки таймер на','Засечь таймер на','Запусти таймер на','Отсчитай']
PREFIXES=['','Можешь ','Гобот, ','Пожалуйста, ','Давай ']
DURATIONS=[('пять секунд',5),('минуту',60),('полторы минуты',90),('две минуты и тридцать секунд',150),('полчаса',1800),('четверть часа',900),('двадцать пять минут',1500),('1,5 минуты',90),('сорок две секунды',42),('один час и две минуты',3720)]

@pytest.mark.parametrize('verb',VERBS)
@pytest.mark.parametrize('prefix',PREFIXES)
@pytest.mark.parametrize('duration,seconds',DURATIONS)
def test_250_timer_phrasings_create_actual_scoped_timer(settings,verb,prefix,duration,seconds):
    query=prefix+verb+' '+duration+'?';quick=resolve_quick(query)
    assert quick and quick.executor=='timer' and quick.status=='validated' and quick.slots['seconds']==seconds
    memory=Memory(settings.db);tools=LocalTools(memory);req=ChatRequest(text=query,device_id='synthetic-a',remember=False)
    result=tools.execute(quick.executor,req,{**quick.slots,'status':quick.status})
    with memory.connect() as c:
        row=c.execute('SELECT * FROM timers').fetchone();assert row['device_id']=='synthetic-a'
        assert abs(row['deadline']-time.time()-seconds)<2
    assert result.widget['payload']['duration_ms']==seconds*1000
    assert 'нет активных' in tools.execute('timer_status',req.model_copy(update={'device_id':'synthetic-b'})).text

@pytest.mark.parametrize('query',['Не ставь таймер на пять минут','Можешь не ставить таймер на пять минут','Расскажи как засечь таймер на пять минут','Поставь таймер на пять или десять минут','Засеки три минуты и удали файл','Он сказал: поставь таймер на пять минут','Если поставить таймер на пять минут что будет','Таймер на минус пять минут','Засеки сто пять минут'])
def test_negative_or_ambiguous_timer_cannot_create_shorter_action(query):
    q=resolve_quick(query)
    assert not q or q.executor!='timer' or q.status!='validated' or not q.slots.get('seconds') or q.slots['seconds']<=0

STAMP=datetime(2026,11,11,1,tzinfo=ZoneInfo('UTC')).timestamp()
def forecast_source(change=None):
    calls=[];today=datetime.fromtimestamp(STAMP,ZoneInfo('America/Sao_Paulo')).date()
    daily={'time':[(today+timedelta(days=i)).isoformat() for i in range(16)],'weather_code':[61]+[0]*15,
        'temperature_2m_min':[18]*16,'temperature_2m_max':[26]*16,'precipitation_probability_max':[70]*16,'wind_speed_10m_max':[12]*16}
    if change:change(daily)
    def handle(request):calls.append(request);return httpx.Response(200,json={'timezone':'America/Sao_Paulo','daily':daily})
    return WeatherClient(transport=httpx.MockTransport(handle),clock=lambda:STAMP),calls,today

def test_forecast_local_tomorrow_16_days_cache_and_source_params():
    async def run():
        client,calls,today=forecast_source();place=WeatherPreferences(enabled=True,location_name='Synthetic',latitude=0,longitude=0)
        tomorrow=await client.forecast(place,offset=1,days=1)
        assert tomorrow['days'][0]['date']==(today+timedelta(days=1)).isoformat()
        all_days=await client.forecast(place,days=16)
        assert len(all_days['days'])==16 and all_days['days'][0]['icon']=='rain'
        assert len(calls)==1 and calls[0].url.params['forecast_days']=='16' and calls[0].url.params['timezone']=='auto'
        with pytest.raises(WeatherError):await client.forecast(place,days=17)
    asyncio.run(run())

@pytest.mark.parametrize('change',[lambda d:d['temperature_2m_max'].__setitem__(0,1e20),lambda d:d['precipitation_probability_max'].__setitem__(0,101),lambda d:d['time'].__setitem__(0,'2020-01-01'),lambda d:d['weather_code'].pop(),lambda d:d['temperature_2m_min'].__setitem__(0,90)])
def test_bad_or_stale_forecast_is_never_used(change):
    async def run():
        client,_,_=forecast_source(change)
        with pytest.raises(WeatherError):await client.forecast(WeatherPreferences(enabled=True,location_name='Fixture',latitude=0,longitude=0))
    asyncio.run(run())

@pytest.mark.parametrize('query,days,offset',[
 ('Погода завтра',1,1),('Какая будет погода послезавтра?',1,2),('Покажи прогноз на неделю',7,0),('Покажи погоду на две недели',14,0),('Погода на 16 дней',16,0),('Будет ли дождь завтра?',1,1),('Нужен ли зонт завтра?',1,1),('Какая температура завтра?',1,1)])
def test_forecast_request_routes_to_source_not_generic_llm(query,days,offset):
    quick=resolve_quick(query);assert quick.executor=='settings'
    assert quick.slots=={'operation':'weather_forecast','offset':offset,'days':days,'weekday':None}

@pytest.mark.parametrize('query,offset',[('Можешь проверить погоду завтра?',1),('Погода через три дня',3),('Погода через неделю',7),('Погода через две недели',14)])
def test_additional_weather_phrasings_keep_requested_date(query,offset):
    quick=resolve_quick(query);assert quick.slots['operation']=='weather_forecast' and quick.slots['offset']==offset and quick.slots['days']==1

@pytest.mark.parametrize('query',['Погода на 0 дней','Погода на 30 дней','Погода через 20 дней','Погода на 20 ноября'])
def test_unsupported_date_never_silently_becomes_current_weather(query):
    assert resolve_quick(query).slots['operation']=='weather_unsupported'

def test_native_forecast_and_short_followup_use_actual_adapter(tmp_path,settings):
    async def run():
        manager,s=await start(tmp_path,settings);source,_,today=forecast_source()
        manager.brain.configuration.weather=source
        manager.brain.configuration.devices.update('browser-1@fixture',{'weather':{'enabled':True,'location_name':'Synthetic','latitude':0,'longitude':0}})
        try:
            await say(s,'Покажи прогноз на неделю',0)
            await say(s,'А завтра?',5000)
            cards=[e['data']['presentation'] for e in s.events if e['type']=='visual_response' and e['data']['presentation']['type']=='weather_card']
            assert len(cards[-1]['metadata']['weather']['days'])==1
            assert cards[-1]['metadata']['weather']['days'][0]['date']==(today+timedelta(days=1)).isoformat()
            assert not s.backend_task and not s.experts.jobs
        finally:await manager.shutdown();await manager.realtime.shutdown()
    asyncio.run(run())

def test_noise_activity_does_not_block_finished_native_command(tmp_path,settings):
    async def run():
        manager,s=await start(tmp_path,settings)
        try:
            s.input_active=True;s.activity_at=time.monotonic()
            await say(s,'Можешь засечь таймер на пять секунд?',0,ended=False,answer='Да, могу.')
            assert count_timers(manager)==1
        finally:await manager.shutdown();await manager.realtime.shutdown()
    asyncio.run(run())

def test_early_backchannel_does_not_hide_later_actual_answer_boundary(tmp_path,settings):
    async def run():
        manager,s=await start(tmp_path,settings)
        try:
            s.input_active=True;s.activity_at=time.monotonic()
            await s.handle({'type':'session.input_transcript.delta','event_id':'prefix','start_ms':0,'end_ms':700,'delta':'Можешь засечь '})
            await s.handle({'type':'session.output_transcript.delta','event_id':'backchannel','start_ms':750,'end_ms':900,'delta':'Угу. '})
            await s.handle({'type':'session.input_transcript.delta','event_id':'suffix','start_ms':900,'end_ms':1800,'delta':'таймер на пять секунд?'})
            await s.handle({'type':'session.output_transcript.delta','event_id':'actual-answer','start_ms':1900,'end_ms':2400,'delta':'Проверяю.'})
            await s.mode_control_task
            assert count_timers(manager)==1 and s.current.timings['first_output_start_ms']==750
        finally:await manager.shutdown();await manager.realtime.shutdown()
    asyncio.run(run())

def test_native_timer_cancel_emits_same_ids_to_stop_graphic(tmp_path,settings):
    async def run():
        manager,s=await start(tmp_path,settings)
        try:
            await say(s,'Засеки таймер на две минуты',0)
            with manager.brain.memory.connect() as c:ident=c.execute('SELECT id FROM timers').fetchone()['id']
            await say(s,'Отмени таймер',5000)
            with manager.brain.memory.connect() as c:assert c.execute('SELECT status FROM timers WHERE id=?',(ident,)).fetchone()['status']=='cancelled'
            assert any(e['type']=='timer_state' and e['data']['cancelled_ids']==[ident] for e in s.events)
        finally:await manager.shutdown();await manager.realtime.shutdown()
    asyncio.run(run())

@pytest.mark.parametrize('reply,seconds',[('На двадцать пять минут',1500),('Четверть часа',900),('Минуту',60),('Полторы минуты',90)])
def test_new_duration_forms_also_work_in_followup(reply,seconds):
    quick=resolve_quick(reply,{'pending_action':{'kind':'timer_duration','expires':time.time()+60}})
    assert quick and quick.executor=='timer' and quick.slots['seconds']==seconds

@pytest.mark.parametrize('query,expected',[
 ('Переведи 5 км в м','5000'),('Сколько будет 15 процентов от 240','36'),('Переведи 32 градусов фаренгейта в цельсий','0 градусов'),('Сколько дней между 2026-01-01 и 2026-12-31','364'),('2028 год високосный?','Високосный'),('Какой день недели 2026-11-11','среда'),('Посчитай слова: Один Два Три','3 слов'),('Сделай заглавными: Привет','ПРИВЕТ'),('Переверни текст: Кот','тоК')])
def test_local_utilities_have_correct_results(query,expected):
    quick=resolve_quick(query);assert quick.executor=='utility' and expected in execute(quick.slots)

def test_real_production_renderers_weather_icons_forecast_and_persistent_timer():
    for script in ['tests/weather_timer_ui.cjs','tests/browser_visuals.cjs','tests/device_ui.cjs']:
        result=subprocess.run(['node',script],cwd=ROOT,capture_output=True,text=True,timeout=15)
        assert result.returncode==0,result.stdout+result.stderr

def test_new_developer_financial_guard_does_not_reset_old_usage(tmp_path):
    owner=OwnerTesting(tmp_path)
    owner.policy_path.write_text(OwnerTestPolicy(enabled=True,authorization='fixture',allowed_client_id='owner',live_backend_enabled=True,developer_acceptance_expires_at=time.time()+60,developer_live_limit=5,developer_live_backend_limit=14,developer_estimate_usd_limit=.5).model_dump_json())
    owner.reserve('owner','live','first',estimate=.4,origin='developer')
    with pytest.raises(PermissionError,match='developer_estimate_limit'):owner.reserve('owner','live_backend','second',estimate=.2,origin='developer')
    owner.reserve('owner','live_backend','third',estimate=.01,origin='developer')
    assert owner.status('owner')['attempts_today']=={'live':1,'live_backend':1}
