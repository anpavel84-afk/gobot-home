"""Timing uses events, not sleeps or real provider quotas."""
import asyncio
import pytest
from fastapi.testclient import TestClient
from gobot import brain
from gobot.context_manager import serialize_context
from gobot.image_query import caption_names_subject
from gobot.models import ChatRequest
from gobot.presentation import Presentation,VisualImage,VisualMetadata,VisualSource,frame_id
from gobot.visual import VisualResult
from gobot.visual_prefetch import extract_entity

QUESTION='В Бразилии растут грибы-лисички?'
ANSWER='В ответе речь идёт о грибах из рода лисичек.'

@pytest.mark.parametrize('question,answer,entity',[
    (QUESTION,ANSWER,'Лисичка (род грибов)'),
    ('Как дышат маленькие паучки?','Пауки дышат по-разному.','Пауки'),
    ('Сколько весит слон?','Масса слона зависит от вида.','слон'),
    ('Где живут белые медведи?','Белые медведи живут в Арктике.','белый медведь'),
    ('Сколько лет живут курицы?','Курицы живут несколько лет.','курица'),
    ('Как устроен телескоп?','Телескоп собирает свет.','телескоп'),
    ('Как приготовить греческий салат?','Для греческого салата нарежь овощи.','греческий салат'),
])
def test_extract_and_ground_plain_russian(question,answer,entity):
    candidate=extract_entity(question)
    assert candidate.query==entity and candidate.confirm(answer)
    assert not candidate.confirm('На фотографии тропическое дерево.')

def test_no_visual_protocol_in_cli_prompt_or_incidental_caption():
    prompt=serialize_context('Тест',{})
    assert 'gobot_visual' not in prompt and 'только пользовательский текст' in prompt
    assert not caption_names_subject('телескоп','NASA’s Webb Telescope NIRSpec Instrument Ready for Science')
    assert caption_names_subject('телескоп','Telescope')
    assert caption_names_subject('солнечная аратинга','DSC09858 - Sun Conure')
    assert not extract_entity('Расскажи о моих пауках')
    assert not extract_entity('Привет!')
    assert not extract_entity(QUESTION).confirm('Лисички здесь не грибы, а маленькие лисы.')

def photo(req,plan):
    key='a'*64;base='/api/visual/assets/'+key+'/'
    image=VisualImage(asset_id=key,url=base+'browser.jpg',preview_variant=base+'preview.jpg',
        device_variant=base+'device.jpg',width=240,height=240,caption='fixture',alt='fixture',
        source=VisualSource(label='fixture'),attribution='fixture',license='fixture')
    frame=Presentation(id=frame_id(req.turn_id,'fixture'),type='image_card',title=plan.subject_label,
        images=[image],metadata=VisualMetadata(visual_strategy='retrieve'))
    return VisualResult(frame,'','')

@pytest.mark.parametrize('picture_first',[True,False])
def test_fetch_overlaps_model_confirmation_gates_display_and_history(settings,monkeypatch,picture_first):
    async def run():
        service=brain.Service(settings)
        searching=asyncio.Event();model_running=asyncio.Event();release=asyncio.Event()
        req=ChatRequest(text=QUESTION,mode='auto',usage_consent=True)
        async def lookup(req,plan,**kwargs):
            searching.set()
            if not picture_first:await model_running.wait()
            return photo(req,plan)
        async def provider(*args):
            assert searching.is_set();yield 'Сейчас поясню. '
            model_running.set()
            yield ANSWER
            await release.wait()
            yield ' Последняя фраза.'
        monkeypatch.setattr(service.visual,'attachment',lookup)
        monkeypatch.setattr(brain,'bridge_stream',provider)
        monkeypatch.setattr(brain,'agent_status',lambda *_:{'antigravity':{'available':True}})
        await service.prepare(req);items=[]
        async with asyncio.timeout(3):
            async for event in service.events(req):
                if event.type=='visual_response':
                    assert any(i.type=='text_delta' and ANSWER in i.data['text'] for i in items)
                    release.set()
                items.append(event)
        frames=[i.data['presentation'] for i in items if i.type=='visual_response']
        assert len(frames)==1 and items[-1].type=='final'
        assert (await service.history(req.conversation_id,req.device_id))['messages'][-1]['presentation']==frames[0]
        assert not (await service.history(req.conversation_id,'someone-else'))['messages']
    asyncio.run(run())

@pytest.mark.parametrize('text', ['Речь идёт о лисятах.','Фотография не подтверждена.'])
def test_unconfirmed_picture_keeps_avatar(settings,monkeypatch,text):
    async def run():
        service=brain.Service(settings)
        async def lookup(req,plan,**kw):return photo(req,plan)
        async def provider(*args):yield text
        monkeypatch.setattr(brain,'bridge_stream',provider)
        monkeypatch.setattr(brain,'agent_status',lambda *_:{'antigravity':{'available':True}})
        monkeypatch.setattr(service.visual,'attachment',lookup)
        req=ChatRequest(text=QUESTION,mode='auto',remember=False);await service.prepare(req)
        frames=[i.data['presentation'] async for i in service.events(req) if i.type=='visual_response']
        assert frames==[]
    asyncio.run(run())

def test_failed_search_returns_to_avatar_without_subject_error_card(settings,monkeypatch):
    async def run():
        service=brain.Service(settings)
        async def lookup(req,plan,**kwargs):
            return service.visual.fallback(req,'Иллюстрация','image_lookup_timeout')
        async def provider(*args):
            yield 'Эндокринная система состоит из желез внутренней секреции. '
            yield 'Гормоны поступают в кровь.'
        monkeypatch.setattr(brain,'bridge_stream',provider)
        monkeypatch.setattr(brain,'agent_status',lambda *_:{'antigravity':{'available':True}})
        monkeypatch.setattr(service.visual,'attachment',lookup)
        req=ChatRequest(text='Как устроена эндокринная система человека?',mode='auto',remember=False)
        events=[item async for item in service.events(req)]
        assert not any(e.type=='visual_response' for e in events)
        scene=next(e.data['scene'] for e in events if e.type=='screen_scene' and e.data['phase']=='answer_complete')
        assert scene['scene_type']=='avatar'
        assert scene['source_metadata']['fallback_reason']=='avatar_when_image_missing'
        assert events[-1].type=='final'
    asyncio.run(run())

def test_history_can_restore_cached_diagram_after_failed_search(settings,monkeypatch):
    async def run():
        service=brain.Service(settings)
        req=ChatRequest(text='Как устроена эндокринная система человека?',mode='auto')
        service.memory.start(req)
        service.memory.finish(req,'completed','Эндокринная система состоит из желез.','fixture',[
            {'optional_visual_error':'optional_visual_unavailable'}])
        async def cached(req,plan,**kwargs):
            assert kwargs=={'cache_only':True}
            return photo(req,plan)
        monkeypatch.setattr(service.visual,'attachment',cached)
        archive=await service.history(req.conversation_id,req.device_id)
        assert archive['messages'][-1]['presentation']['images']
        assert 'presentation' not in service.memory.history(req.conversation_id,req.device_id)['messages'][-1]
        assert not (await service.history(req.conversation_id,'another-owner'))['messages']
    asyncio.run(run())

def test_file_stt_final_starts_one_lookup_reused_by_turn(settings,monkeypatch):
    calls=[]
    async def stt(*args,**kwargs):return {'text':QUESTION,'provider':'openai','stt_ms':1}
    async def provider(*args):
        assert len(calls)==1
        yield ANSWER
    async def lookup(req,plan,**kw):
        calls.append((req.turn_id,plan.visual_query))
        return photo(req,plan)
    monkeypatch.setattr(brain.Speech,'transcribe',stt)
    monkeypatch.setattr(brain.SpeakerIdentity,'submit_recording',lambda *args:None)
    monkeypatch.setattr(brain,'bridge_stream',provider)
    monkeypatch.setattr(brain,'agent_status',lambda *_:{'antigravity':{'available':True}})
    app=brain.create_app(settings);monkeypatch.setattr(app.state.service.visual,'attachment',lookup)
    headers={'Authorization':'Bearer '+settings.api_token}
    with TestClient(app) as client:
        resp=client.post('/api/v1/audio/transcribe',params={'visual_prefetch':True,'trace_id':'voice-1'},
            content=b'fixture',headers=headers)
        assert resp.status_code==200
        events=client.post('/api/v1/chat',json={'text':QUESTION,'utterance_id':'voice-1','turn_id':'question-1',
            'mode':'auto','remember':False,'usage_consent':True},headers=headers).json()['events']
        assert calls==[('voice-1','Лисичка (род грибов)')]
        frame=next(e['data']['presentation'] for e in events if e['type']=='visual_response')
        assert frame['id']==frame_id('question-1','attachment')
        assert any(t.get('started_at')=='stt_final' for t in events[-1]['data']['trace'])

def test_handoff_bound_to_owner_and_unedited_text(settings):
    async def run():
        service=brain.Service(settings)
        req=ChatRequest(text=QUESTION,device_id='first',utterance_id='u')
        service.warm_from_final(QUESTION,'first','u',None)
        assert service.claim_warm(req.model_copy(update={'device_id':'second'})) is None
        assert service.claim_warm(req.model_copy(update={'profile_epoch':'changed'})) is None
        task=service.warm_photos[('first',None,'u')][1]
        assert service.claim_warm(req.model_copy(update={'text':'Другой вопрос'})) is None
        await asyncio.gather(task,return_exceptions=True)
        assert task.cancelled() and not service.warm_photos
    asyncio.run(run())

def test_live_transcript_starts_prefetch_only_on_final(settings,monkeypatch):
    from gobot.stt import OpenAIRecognition
    calls=[]
    async def live(self,chunks,**kwargs):
        yield {'type':'stt_partial','data':{'text':'Лис'}}
        async for _ in chunks:break
        yield {'type':'stt_final','data':{'text':QUESTION}}
    monkeypatch.setattr(OpenAIRecognition,'live',live)
    monkeypatch.setattr(brain.SpeakerIdentity,'submit',lambda *args:None)
    app=brain.create_app(settings)
    monkeypatch.setattr(app.state.service,'warm_from_final',lambda text,*args:calls.append(text))
    with TestClient(app) as client:
        with client.websocket_connect('/api/v1/audio/live',headers={'Authorization':'Bearer '+settings.api_token}) as ws:
            ws.send_json({'visual_prefetch':True,'trace_id':'utterance'})
            assert ws.receive_json()['type']=='stt_partial' and calls==[]
            ws.send_bytes(b'\0\0'*100)
            assert ws.receive_json()['type']=='stt_final' and calls==[QUESTION]
