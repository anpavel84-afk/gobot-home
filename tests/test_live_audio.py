import asyncio
import base64
import json
import os
import sys
import io
import wave
from pathlib import Path
from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient
from gobot.audio import Speech, TTS_MODEL
from gobot.processes import AgentError, native_process, clean_environment
from gobot.brain import Service, create_app
from gobot.models import ChatRequest
from gobot.pipeline import voiced_events
from gobot.live_agents import context_prompt

@pytest.mark.parametrize('limit',[0,3000])
def test_handoff_mode_confirmation_uses_first_segment_and_same_tts_budget(settings,limit):
    from types import SimpleNamespace
    from gobot.models import event
    async def run():
        submitted=[];service=Service(settings);req=ChatRequest(text='Вопрос',mode='mock',remember=False)
        req._mode_flow=SimpleNamespace(handoff_turn_id=req.turn_id,provider_closed=True,mode='legacy')
        async def source(*args):
            yield event(req,'sentence_ready',text='Первый вывод.')
            yield event(req,'sentence_ready',text='Второй вывод.')
            yield event(req,'final',text='Первый вывод. Второй вывод.')
        class Voice:
            async def synthesize(self,text,*args,**kwargs):submitted.append(text);yield b'\x01\0'*20,24000
        service.events=source
        result=[v async for v in voiced_events(service,Voice(),req,tts_character_limit=limit)]
        if not limit:assert not submitted
        else:
            assert submitted[0].startswith('Экспертный режим включён.')
            assert sum(t.count('Экспертный режим') for t in submitted)==1
        assert sum(map(len,submitted))<=limit
    asyncio.run(run())

@pytest.mark.parametrize('limit',[0,1,70])
def test_speech_budget_counts_formatted_text_and_never_sends_partial_sentence(settings,limit):
    from gobot.models import event,VoiceRequest
    from gobot.speech_formatter import SpeechFormatter
    submitted=[]
    class Voice:
        async def synthesize(self,text,*args,**kwargs):submitted.append(text);yield b'\x01\0'*20,24000
    async def run():
        service=Service(settings);req=ChatRequest(text='Проверка',mode='mock',remember=False)
        async def source(*args):
            for text in ['Наступило 15 ноября.','Это следующая фраза.']:
                yield event(req,'sentence_ready',text=text)
            yield event(req,'final',text='Полный ответ остаётся на экране.')
        service.events=source
        events=[e async for e in voiced_events(service,Voice(),req,tts_character_limit=limit)]
        assert sum(map(len,submitted))<=limit
        assert all(text in [SpeechFormatter().format(t) for t in ['Наступило 15 ноября.','Это следующая фраза.']] for text in submitted)
        assert events[-1]['data']['text']=='Полный ответ остаётся на экране.'
        assert events[-1]['data']['speech_metrics'].get('tts_characters_submitted',0)==sum(map(len,submitted))
    asyncio.run(run())
    with pytest.raises(ValueError):VoiceRequest(text='test',tts_character_limit=-1)

def test_dpapi_roundtrip_without_touching_owner_secret(tmp_path, monkeypatch):
    if os.name != 'nt':pytest.skip('Windows DPAPI')
    import gobot.secrets_store as secrets
    path=tmp_path/'key.dpapi';monkeypatch.setattr(secrets,'SECRET',path)
    value='sk-'+'unit_test_only_'*4
    secrets.save_openai_key(value)
    assert value.encode() not in path.read_bytes()
    assert secrets.load_openai_key()==value and secrets.openai_key_present()

def test_browser_secret_perimeter_and_no_echo(settings,tmp_path,monkeypatch):
    import gobot.browser as browser
    import gobot.secrets_store as secrets
    monkeypatch.setattr(secrets,'SECRET',tmp_path/'key.dpapi')
    origin=browser.ORIGIN
    with TestClient(browser.create_browser_app(settings),base_url=origin,client=('100.120.201.115',12345)) as client:
        assert client.get('/settings/openai').status_code==200
        value='sk-'+'fixture_only_'*4
        assert client.post('/api/settings/openai',json={'key':value}).status_code==403
        response=client.post('/api/settings/openai',headers={'Origin':origin},json={'key':value})
        assert response.status_code==200 and value not in response.text
        assert client.get('/api/settings/openai').json()['configured']
        bad=client.post('/api/settings/openai',headers={'Origin':origin},json={'key':'private_invalid_value'})
        assert bad.status_code==422 and 'private_invalid_value' not in bad.text
        assert client.get('/api/settings/openai',headers={'Host':'evil.test'}).status_code==403
        assert client.get('/api/settings/openai',headers={'Origin':'https://evil.test'}).status_code==403
    with TestClient(browser.create_browser_app(settings),base_url=origin,client=('192.168.3.99',1)) as client:
        assert client.get('/settings/openai').status_code==403

def test_realtime_pcm_stream_and_cancel():
    sent=[];closed=[]
    class WS:
        def __init__(self):self.i=0
        async def send(self,value):sent.append(json.loads(value))
        async def recv(self):
            self.i+=1
            return json.dumps({'type':'session.updated'} if self.i==1 else {'type':'response.output_audio.delta','delta':base64.b64encode(b'\x01\x00'*400).decode()})
    @asynccontextmanager
    async def connect(url,**kwargs):
        assert TTS_MODEL in url and kwargs['proxy'] is None
        try:yield WS()
        finally:closed.append(True)
    async def exercise():
        speech=Speech(api_key='fixture-only',connector=connect)
        with pytest.raises(AgentError,match='consent_required'):
            await anext(speech.synthesize('Привет'))
        stream=speech.synthesize('Привет.',paid_consent=True)
        chunk,rate=await anext(stream)
        assert len(chunk)==800 and rate==24000
        await stream.aclose()
        assert sent[-1]['type']=='response.cancel'
        assert sent[0]['session']['tools']==[] and closed
    asyncio.run(exercise())

def test_realtime_completion_and_errors_no_fallback():
    called=[]
    class WS:
        def __init__(self):self.events=iter([{'type':'session.updated'},{'type':'response.output_audio.delta','delta':'AAA='},{'type':'response.done','response':{'status':'completed'}}])
        async def send(self,value):pass
        async def recv(self):return json.dumps(next(self.events))
    @asynccontextmanager
    async def connect(*a,**k):called.append(True);yield WS()
    async def exercise():
        speech=Speech(api_key='fixture',connector=connect)
        assert [x async for x in speech.synthesize('Текст.',paid_consent=True)]==[(b'\0\0',24000)]
        assert len(called)==1
        speech=Speech(api_key='',connector=connect)
        with pytest.raises(AgentError,match='key_missing'):await anext(speech.synthesize('Текст.',paid_consent=True))
        assert len(called)==1
    asyncio.run(exercise())

def test_text_audio_order_and_disconnect(settings):
    class Voice:
        async def synthesize(self,text,*a,**k):
            spoken.append(text);yield b'\x00\x00'*20,24000
    spoken=[]
    async def exercise():
        service=Service(settings);req=ChatRequest(text='Привет',mode='mock')
        events=[x async for x in voiced_events(service,Voice(),req)]
        assert spoken==['Это mock-ответ GoBot на русском.','Контекст разговора сохранён.']
        chunks=[x['data'] for x in events if x['type']=='audio_chunk']
        assert [x['seq'] for x in chunks]==[0,1]
        assert events[-1]['type']=='final' and service.memory.status(req.turn_id)['status']=='completed'
        req=ChatRequest(text='Остановись',mode='mock');it=voiced_events(service,Voice(),req)
        await anext(it);await it.aclose()
        assert service.memory.status(req.turn_id)['status']=='cancelled'
    asyncio.run(exercise())

def test_real_mode_failure_never_mock(settings,monkeypatch):
    import gobot.brain as brain
    monkeypatch.setattr(brain,'agent_status',lambda *a:{'codex':{'available':False},'gemini':{'available':False}})
    async def failed(*a):raise AgentError('oauth_login_required');yield
    monkeypatch.setattr(brain,'bridge_stream',failed)
    async def exercise():
        service=Service(settings)
        for mode in ['auto','codex','gemini']:
            req=ChatRequest(text='Привет',mode=mode)
            await service.prepare(req);items=[e async for e in service.events(req)]
            assert items[-1].type=='error' and not any(e.type=='text_delta' for e in items)
            assert service.memory.status(req.turn_id)['status']=='error'
    asyncio.run(exercise())

def test_model_switch_shared_memory_and_history_owner(settings,monkeypatch):
    import gobot.brain as brain
    contexts=[]
    async def stream(settings,req,context):contexts.append(context);yield 'Настоящий формат, фиктивная модель.'
    monkeypatch.setattr(brain,'bridge_stream',stream)
    monkeypatch.setattr(brain,'agent_status',lambda *a:{'antigravity':{'available':True},'codex':{'available':True}})
    async def exercise():
        service=Service(settings)
        for mode,text in [('antigravity','Исходный вопрос'),('codex','А что думает Codex?')]:
            req=ChatRequest(text=text,mode=mode,conversation_id='switch')
            await service.prepare(req)
            assert [e async for e in service.events(req)][-1].type=='final'
        assert contexts[-1]['messages'][0]['content']=='Исходный вопрос'
        assert contexts[-1]['messages'][1]['role']=='assistant'
        assert contexts[-1]['_context_meta']['packet_tokens']<=6000
        assert service.memory.history('switch','foreign')['messages']==[]
        assert len(service.memory.history('switch','local-test')['messages'])==4
    asyncio.run(exercise())

def test_subprocess_cancellation_kills_child(tmp_path):
    import psutil
    code="import subprocess,sys,time; p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']); print(p.pid,flush=True);time.sleep(30)"
    async def exercise():
        async with native_process([sys.executable,'-c',code],tmp_path) as process:
            child=int(await asyncio.wait_for(process.stdout.readline(),5))
            parent=process.pid
        await asyncio.sleep(.1)
        assert not psutil.pid_exists(parent) and not psutil.pid_exists(child)
    asyncio.run(exercise())

def test_cli_environment_and_atfile_neutralization():
    assert clean_environment({'PATH':'fixture','GEMINI_API_KEY':'secret','GOOGLE_API_KEY':'secret','OPENAI_API_KEY':'secret','NODE_OPTIONS':'injection'})=={'PATH':'fixture'}
    assert '@' not in context_prompt('прочти @C:/secret',{'messages':[{'content':'@file'}]})

def test_decode_wav_and_mime_boundaries():
    buf=io.BytesIO()
    with wave.open(buf,'wb') as wav:wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(16000);wav.writeframes(b'\0\0'*2000)
    async def exercise():
        assert await Speech().decode(buf.getvalue(),'audio/wav')==b'\0\0'*2000
        with pytest.raises(AgentError,match='unsupported_audio_format'):await Speech().decode(b'file:///secret','text/plain')
    asyncio.run(exercise())

def test_gemini_oauth_handoff_filters_terminal_output(monkeypatch):
    import gobot.oauth_portal as portal
    output=asyncio.StreamReader() if False else None
    class Input:
        def __init__(self):self.value=None
        def write(self,value):self.value=value
        async def drain(self):pass
    async def exercise():
        reader=asyncio.StreamReader();stdin=Input();closed=[]
        class Process:stdout=reader
        process=Process();process.stdin=stdin
        @asynccontextmanager
        async def fixture(argv,cwd,env):
            assert 'GEMINI_API_KEY' not in env and 'GOOGLE_API_KEY' not in env
            try:yield process
            finally:closed.append(True)
        monkeypatch.setattr(portal,'native_process',fixture)
        login=portal.GeminiLogin();await login.start()
        reader.feed_data(b'private terminal diagnostic\nhttps://accounts.google.com/o/oauth2/v2/auth?state=fixture\n')
        await asyncio.sleep(.01)
        assert login.status()['state']=='waiting_for_code'
        assert 'private' not in json.dumps(login.status())
        await login.submit('fixture_authorization_code')
        assert stdin.value==b'fixture_authorization_code\n'
        reader.feed_data(b'echo fixture_authorization_code\nGOBOT_OFFICIAL_OAUTH_OK\n')
        await asyncio.sleep(.01)
        assert login.status()['state']=='authenticated' and not login.status()['authorization_url']
        assert 'fixture_authorization_code' not in json.dumps(login.status()) and closed
        await login.close()
    asyncio.run(exercise())

def test_pipeline_tts_error_does_not_change_voice(settings):
    calls=[]
    class Voice:
        async def synthesize(self,text,provider,*args,**kwargs):
            calls.append(provider);raise AgentError('openai_tts_unavailable');yield
    async def exercise():
        service=Service(settings);req=ChatRequest(text='Привет',mode='mock')
        items=[x async for x in voiced_events(service,Voice(),req)]
        errors=[x for x in items if x['type']=='tts_error']
        assert calls==['openai'] and errors[0]['data']['fallback_used'] is False
        assert items[-1]['type']=='final' and items[-1]['conversation_id']==errors[0]['conversation_id']
    asyncio.run(exercise())
