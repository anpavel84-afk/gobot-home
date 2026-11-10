import asyncio,io,json,math,wave
from contextlib import asynccontextmanager
import httpx,pytest
from fastapi.testclient import TestClient
from gobot.family import Family
from gobot.memory import Memory
from gobot.models import ChatRequest
from gobot.speaker import SpeakerIdentity,quality
from gobot.stt import OpenAIRecognition,FILE_MODEL,LIVE_MODEL
from gobot.processes import AgentError

@pytest.fixture
def family(settings):return Family(Memory(settings.db))

def calibrated(family):
    profiles=[]
    for i in range(5):
        ident=family.create('Тест '+str(i),'adult','fixture-pin',consent=True)['id'];profiles.append(ident)
        vector=[float(j==i) for j in range(8)]
        for _ in range(3):family.store(ident,vector,10)
        for _ in range(2):family.store(ident,vector,7,'validation')
        family.enable(ident,True)
    family.store(None,[0.0]*7+[1.0],7,'unknown');family.calibrate();return profiles

def test_five_profiles_known_unknown_similar_restart(family,settings):
    profiles=calibrated(family)
    assert len(family.profiles())==5
    for i,ident in enumerate(profiles):
        result=family.identify([float(j==i) for j in range(8)])
        assert result['state']=='recognized' and result['profile_id']==ident
        assert result['personal_authorized'] is False and 'confidence' not in result
    assert family.identify([0.0]*7+[1.0])['state']=='unknown'
    assert family.identify([1.,1.]+[0.]*6)['state']=='ambiguous'
    assert Family(Memory(settings.db)).identify([1.]+[0.]*7)['profile_id']==profiles[0]

def test_templates_encrypted_deleted_and_opt_in(family):
    with pytest.raises(ValueError,match='parent_consent'):family.create('Ребёнок','child','fixture-pin',consent=True)
    child=family.create('Ребёнок','child','fixture-pin',consent=True,parent_consent=True)['id']
    family.store(child,[1.,0.],10)
    with family.memory.connect() as c:blob=c.execute('SELECT vector FROM voice_vectors').fetchone()[0]
    assert b'[1.0, 0.0]' not in blob
    family.reset_voice(child)
    assert family.vectors()==[]
    family.delete(child);assert family.profiles()==[]
    ident=family.create('Без биометрии','adult','fixture-pin')['id']
    with pytest.raises(ValueError,match='biometric_consent'):family.store(ident,[1.,0.],10)

def test_no_arbitrary_threshold_and_overlap(family):
    ident=family.create('Один','adult','fixture-pin',consent=True)['id']
    family.store(ident,[1.,0.],10)
    assert family.identify([1.,0.])['reason']=='calibration_required'
    with pytest.raises(ValueError):family.calibrate()

def test_personal_history_never_crosses_unknown_or_other_profile(family):
    first=family.create('Первый','adult','fixture-pin')['id'];second=family.create('Второй','adult','fixture-pin')['id']
    memory=family.memory
    req=ChatRequest(text='Личная беседа',conversation_id='private',device_id='personal:'+first)
    memory.start(req);memory.finish(req,'completed','Личный ответ','fixture',[])
    assert memory.context(req)['messages']
    for device in ['browser-unknown','personal:'+second,'family:home']:
        other=req.model_copy(update={'device_id':device})
        assert memory.context(other)['messages']==[] and memory.history('private',device)['messages']==[]
    memory.add_fact('family:home','Общий факт',True)
    assert memory.context(ChatRequest(text='x',device_id='browser-unknown'))['facts']==['Общий факт']
    assert family.verify_pin(first,'fixture-pin')['id']==first
    with pytest.raises(ValueError):family.verify_pin(first,'wrong-pin')

def test_too_short_quiet_noise_quality():
    import numpy as np
    assert quality(b'\0\0'*16000)['state']=='insufficient_audio'
    assert quality(b'\0\0'*64000)['reason']=='too_quiet'
    noise=(np.random.default_rng(42).normal(0,.12,16000*6).clip(-1,1)*32767).astype('<i2').tobytes()
    assert quality(noise)['state']=='insufficient_audio'

def test_openai_file_model_consent_no_fallback():
    calls=[]
    async def handler(request):
        calls.append(request)
        assert FILE_MODEL.encode() in request.content and b'languages[]' in request.content and b'whisper' not in request.content
        return httpx.Response(200,json={'text':'Привет, семья!','languages':[{'code':'ru'}]})
    async def exercise():
        client=OpenAIRecognition(api_key='fixture',transport=httpx.MockTransport(handler))
        with pytest.raises(AgentError,match='consent_required'):await client.file(b'x'*100,'audio/wav')
        assert calls==[]
        result=await client.file(b'x'*100,'audio/wav',paid_consent=True)
        assert result['text']=='Привет, семья!' and result['model']==FILE_MODEL
    asyncio.run(exercise())

def test_live_deltas_before_end_final_after_commit():
    sent=[]
    class WS:
        def __init__(self):self.q=asyncio.Queue()
        async def send(self,raw):
            item=json.loads(raw);sent.append(item)
            if item['type']=='session.update':await self.q.put({'type':'session.updated'})
            if item['type']=='input_audio_buffer.append':await self.q.put({'type':'conversation.item.input_audio_transcription.delta','delta':'При','item_id':'1'})
            if item['type']=='input_audio_buffer.commit':await self.q.put({'type':'conversation.item.input_audio_transcription.completed','transcript':'Привет','item_id':'1'})
        async def recv(self):return json.dumps(await self.q.get())
    @asynccontextmanager
    async def connect(url,**kwargs):
        assert url.endswith('intent=transcription') and '?model=' not in url;yield WS()
    async def exercise():
        finish=asyncio.Event()
        async def chunks():yield b'\0\0'*2400;await finish.wait()
        stream=OpenAIRecognition(api_key='fixture',connector=connect).live(chunks(),paid_consent=True)
        assert (await anext(stream))['type']=='stt_ready'
        partial=await anext(stream);assert partial['type']=='stt_partial' and partial['data']['stable'] is False
        assert not any(x['type']=='input_audio_buffer.commit' for x in sent)
        finish.set();final=await anext(stream);assert final['type']=='stt_final' and final['data']['text']=='Привет'
        assert sent[0]['session']['audio']['input']['transcription']['model']==LIVE_MODEL
        assert sent[0]['session']['audio']['input']['turn_detection'] is None
        await stream.aclose()
    asyncio.run(exercise())

def test_identity_does_not_block_stt(settings,monkeypatch):
    from gobot.brain import create_app
    import gobot.brain as brain
    finished=[]
    async def slow_identity(self,pcm):await asyncio.sleep(.5);finished.append(True);return {'state':'unknown'}
    async def decode(*args):return b'\0\0'*64000
    async def stt(*args,**kwargs):return {'text':'Фикстура','provider':'openai','stt_ms':1}
    monkeypatch.setattr(brain.SpeakerIdentity,'identify',slow_identity)
    monkeypatch.setattr(brain.Speech,'decode',decode)
    monkeypatch.setattr(brain.Speech,'transcribe',stt)
    with TestClient(create_app(settings)) as client:
        response=client.post('/api/v1/audio/transcribe',content=b'fixture',headers={'Authorization':'Bearer '+settings.api_token,'Content-Type':'audio/wav'})
        assert response.status_code==200 and response.json()['speaker_job_id']
        assert response.json()['speaker']['reason']=='identity_pending' and finished==[]

def test_manual_provider_switch_and_openai_default(settings,monkeypatch):
    from gobot.audio import Speech
    async def run():
        speech=Speech()
        assert speech.status()['stt']['provider']=='openai' and speech.status()['stt']['automatic_fallback'] is False
        result=await speech.transcribe(b'fixture','audio/wav','mock')
        assert result['provider']=='mock'
        with pytest.raises(AgentError,match='consent_required'):await speech.transcribe(b'fixture','audio/wav')
    asyncio.run(run())
