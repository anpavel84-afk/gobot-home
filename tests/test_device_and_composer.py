import asyncio,io,json,time,subprocess
from pathlib import Path
from types import SimpleNamespace
from PIL import Image
from fastapi.testclient import TestClient
import pytest
from gobot.device_store import DeviceStore
from gobot.device_contract import ScreenPreferences,DeviceProfile
from gobot.response_composer import VisualResponseComposer
from gobot.models import ChatRequest
from gobot.activation import WakeWordActivationService

def test_device_profiles_persist_and_owner_isolated(tmp_path):
    store=DeviceStore(tmp_path/'devices');one=store.profile('one');two=store.profile('two')
    assert one.client_id!=two.client_id
    store.update('one',{'skin':{'skin_id':'soft','face_color':'#ffffff'},'screen':{'automatic_illustrations':False}})
    restored=DeviceStore(tmp_path/'devices').profile('one')
    assert restored.skin.skin_id=='soft' and restored.client_id==one.client_id and not restored.screen.automatic_illustrations
    assert store.profile('two').skin.skin_id=='classic'
    with pytest.raises(ValueError):store.update('one',{'skin':{'javascript':'alert(1)'}})
    with pytest.raises(ValueError):store.update('one',{'client_id':two.client_id})

def test_private_screensaver_validation_and_delete(tmp_path):
    store=DeviceStore(tmp_path/'devices');buffer=io.BytesIO();Image.new('RGB',(400,300),'blue').save(buffer,'PNG')
    profile=store.upload('one',buffer.getvalue(),'image/png');assert profile.has_screensaver
    with Image.open(io.BytesIO(store.image('one'))) as image:assert image.size==(240,240) and not image.getexif()
    with pytest.raises(KeyError):store.image('two')
    with pytest.raises(ValueError):store.upload('one',b'<svg><script/></svg>','image/svg+xml')
    store.remove_image('one');assert not DeviceStore(tmp_path/'devices').profile('one').has_screensaver
    with pytest.raises(KeyError):store.image('one')

def test_device_http_perimeter_profile_and_assets(settings):
    import gobot.browser as browser
    with TestClient(browser.create_browser_app(settings),base_url=browser.ORIGIN,client=('100.120.201.115',200)) as client:
        assert client.get('/device').status_code==200
        profile=client.get('/api/device/profile').json()
        assert not profile['activation']['configured'] and not profile['capabilities']['physical_device_connected']
        assert client.post('/api/device/profile',json={'skin':{'skin_id':'soft'}}).status_code==403
        headers={'Origin':browser.ORIGIN}
        assert client.post('/api/device/profile',headers=headers,json={'skin':{'skin_id':'minimal'}}).status_code==200
        assert client.get('/api/device/profile').json()['profile']['skin']['skin_id']=='minimal'
        assert client.post('/api/device/screensaver',headers={**headers,'Content-Type':'text/html'},content=b'<html>bad').status_code==422
        assert client.get('/manifest.webmanifest').status_code==200

CASES=[
 ('Привет, ГоБот!','Привет!','show_avatar',None),('Как дела?','Всё хорошо.','show_avatar',None),
 ('Спасибо','Пожалуйста.','show_avatar',None),('Доброе утро','Доброе утро!','show_avatar',None),
 ('Расскажи анекдот','Короткая шутка.','show_avatar',None),
 ('Какие сегодня праздники?','Нет проверенных данных.','render_widget','verification'),
 ('Какой сегодня праздник в Бразилии?','Нет проверенных данных.','render_widget','verification'),
 ('Как приготовить греческий салат?','Нарежьте овощи и добавьте фету.','retrieve_photo',None),
 ('Сколько лет живут курицы?','Продолжительность зависит от породы.','retrieve_photo',None),
 ('Сколько лет живут собаки?','Это зависит от породы.','retrieve_photo',None),
 ('Что такое орхидея?','Орхидея — растение.','retrieve_photo',None),
 ('Как устроен томатный куст?','У куста есть корни и стебель.','render_diagram',None),
 ('Где находится Бразилия?','Это страна Южной Америки.','show_emoji_or_icon',None),
 ('Назови столицу Франции','Столица — Париж.','show_emoji_or_icon',None),
 ('Расскажи об истории Рима','Это рассказ о древней истории.','show_emoji_or_icon',None),
 ('Что такое кратер Луны?','Это углубление.','render_diagram',None),
 ('Какое расстояние до Луны?','Оно меняется.','render_diagram',None),
 ('Что такое солнечное затмение?','Луна между Солнцем и Землёй.','render_diagram',None),
 ('Что такое вулкан?','Магма выходит на поверхность.','render_diagram',None),
 ('Что такое Млечный Путь?','Это наша галактика.','generate_illustration',None),
 ('Поставь таймер на пять минут','Таймер запущен.','render_widget','timer'),
 ('Какая сейчас погода?','Источник не подключён.','render_widget',None),
 ('Что сейчас играет?','Источник не подключён.','render_widget',None),
 ('Сколько будет 127 × 43?','Получается 5461.','render_widget','calculator'),
 ('Что мы вчера обсуждали?','Для истории нужен PIN.','render_widget','memory'),
 ('Сравни технические архитектуры','Это техническое объяснение.','show_emoji_or_icon',None),
 ('Объясни программирование','Программы выполняют инструкции.','show_emoji_or_icon',None),
 ('Расскажи интересное','Пингвины живут в разных местах.','show_emoji_or_icon',None),
 ('Чем отличается бычье сердце от обычных помидоров?','Сравним форму.','generate_illustration',None),
 ('Покажи Raspberry Pi','Подготовил фото.','retrieve_photo',None),
 ('Как выглядит пончик?','Подготовил фото.','retrieve_photo',None),
 ('Покажи статус системы','Brain работает.','render_widget',None),
]
@pytest.mark.parametrize('query,answer,strategy,tool',CASES)
def test_thirty_two_synthetic_content_aware_scenes(query,answer,strategy,tool):
    req=ChatRequest(text=query,mode='mock',screen_preferences=ScreenPreferences(style='balanced'));route=SimpleNamespace(tool=tool,quality={})
    scene=VisualResponseComposer().compose(req,route=route,answer=answer)
    assert scene.visual_strategy==strategy and scene.display_text==answer
    assert scene.speech_text is None # Existing Speech Formatter remains the sole default speech renderer.
    assert 'verified' not in scene.source_metadata or not scene.source_metadata['verified']

def test_visual_preferences_do_not_disable_explicit_or_system_ui():
    composer=VisualResponseComposer();pref=ScreenPreferences(automatic_illustrations=False)
    assert not composer.plan(ChatRequest(text='Что такое кратер Луны?',screen_preferences=pref)).visual_needed
    assert composer.plan(ChatRequest(text='Покажи кратер',screen_preferences=pref)).visual_needed
    scene=composer.compose(ChatRequest(text='Поставь таймер',screen_preferences=pref),route=SimpleNamespace(tool='timer',quality={}))
    assert scene.scene_type=='widget'

def test_wake_not_configured_has_no_standby_external_calls():
    gate=WakeWordActivationService()
    assert not gate.status()['configured']
    with pytest.raises(RuntimeError):gate.enable()
    for _ in range(1000):assert gate.feed(b'\0\0'*1000) is None
    assert not gate.buffer and gate.status()['external_calls_in_standby']==0

def test_wake_fixture_ring_buffer_tts_guard_and_cooldown():
    class Detector:
        trigger=False
        def feed(self,pcm):return self.trigger
    detector=Detector();now=[1.0];gate=WakeWordActivationService(detector,verified_russian_model=True,clock=lambda:now[0]);gate.enable()
    for _ in range(100):gate.feed(b'\0\0'*800)
    assert len(gate.buffer)==64000
    detector.trigger=True;assert gate.feed(b'\0\0',tts_playing=True) is None and not gate.buffer
    now[0]+=1;result=gate.feed(b'\0\0'*10);assert result['requires_question_vad']
    assert gate.feed(b'\0\0'*10) is None
    gate.disable();assert not gate.buffer

def test_device_renderer_node_units():
    root=Path(__file__).resolve().parents[1]
    result=subprocess.run(['node','tests/device_ui.cjs'],cwd=root,capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stderr

def test_capture_activity_lifecycle_node_units():
    root=Path(__file__).resolve().parents[1]
    result=subprocess.run(['node','tests/capture_activity.cjs'],cwd=root,capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stderr

def test_followup_vad_without_external_requests():
    root=Path(__file__).resolve().parents[1]
    result=subprocess.run(['node','tests/followup_vad.cjs'],cwd=root,capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stderr

def test_device_uses_actual_shared_browser_client():
    root=Path(__file__).resolve().parents[1]
    result=subprocess.run(['node','tests/device_shared_client.cjs'],cwd=root,capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stderr
