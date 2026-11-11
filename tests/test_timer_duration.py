import time
import pytest
from fastapi.testclient import TestClient
from gobot.brain import create_app
from gobot.timer_duration import timer_seconds,is_timer_duration_reply,duration_text
from gobot.routing import SmartRouter
from gobot.models import ChatRequest

@pytest.mark.parametrize('text,seconds',[
    ('Таймер на 5 мин',300),('Таймер на 5мин.',300),('Таймер на пять минут',300),
    ('Поставь таймер на 30 сек.',30),('Таймер на 10 с',10),('Таймер на 2 ч.',7200),
    ('Таймер на 1 час 30 мин',5400),('Таймер на 1 мин. и 30 сек.',90),
    ('Таймер на полчаса',1800),('Таймер на 1,5 мин.',90),
    ('Таймер на -5 мин',0),('Таймер на минус 5 мин',0),
    ('Таймер на 0 мин',0),('Таймер на 5 минералов',None),
    ('Таймер на 5 мин или 10 мин',None),('Таймер на двадцать пять минут',1500),
    ('Таймер на 999999999999999999999 мин',None),
])
def test_timer_units(text,seconds):assert timer_seconds(text)==seconds

@pytest.mark.parametrize('text',['5 мин','5мин.','на пять минут','30 сек.','2 ч','1 мин 30 сек','полчаса'])
def test_pending_duration_routes_locally(text):
    req=ChatRequest(text=text,mode='auto')
    context={'pending_action':{'kind':'timer_duration','expires':time.time()+60}}
    assert is_timer_duration_reply(text)
    assert SmartRouter().choose(req,context,{}).tool=='timer'

def test_duration_reply_does_not_capture_other_tasks():
    assert not is_timer_duration_reply('Расскажи, как варить яйца 5 мин')
    assert not is_timer_duration_reply('5 минут назад что я спрашивал?')

@pytest.mark.parametrize('seconds,expected',[(60,'1 минуту'),(120,'2 минуты'),(300,'5 минут'),(660,'11 минут'),(1260,'21 минуту'),(90,'1 минуту 30 секунд')])
def test_timer_display_grammar(seconds,expected):assert duration_text(seconds)==expected

def test_screenshot_request_returns_real_timer_card(settings):
    app=create_app(settings);headers={'Authorization':'Bearer '+settings.api_token}
    with TestClient(app) as client:
        request={'text':'Таймер на 5 мин','mode':'auto','device_id':'test-timer','remember':False}
        result=client.post('/api/v1/chat',headers=headers,json=request)
        assert result.status_code==200
        events=result.json()['events'];final=events[-1]
        assert final['type']=='final' and final['data']['provider']=='local'
        assert final['data']['text']=='Таймер запущен на 5 минут.'
        frame=next(e['data']['presentation'] for e in events if e['type']=='visual_response')
        assert frame['type']=='timer_widget' and frame['metadata']['duration_ms']==300000
        assert 295<frame['metadata']['deadline']-time.time()<=300
        with app.state.service.memory.connect() as c:assert c.execute('SELECT count(*) FROM timers').fetchone()[0]==1
