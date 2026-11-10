import asyncio
from types import SimpleNamespace
import pytest
from gobot.presentation_planner import MultimodalResponsePlanner,PresentationPolicy
from gobot.providers import merge_presentation
from gobot.brain import Service
from gobot.models import ChatRequest
from gobot.pipeline import voiced_events

@pytest.mark.parametrize('text,strategy,priority,template',[
 ('Покажи кратер','retrieve','required',None),
 ('Что такое кратер Луны?','generate','helpful','lunar_crater'),
 ('Какое расстояние до Луны?','generate','helpful','earth_moon'),
 ('Что такое солнечное затмение?','generate','helpful','solar_eclipse'),
 ('Как выглядит пончик?','retrieve','required',None),
 ('Какая сейчас погода?','render_local','required',None),
 ('Чем отличается бычье сердце от обычных помидоров?','generate','helpful','tomato_comparison'),
 ('Покажи Raspberry Pi','retrieve','required',None),
 ('Покажи схему солнечного затмения','generate','required','solar_eclipse'),
 ('Чем отличается лабрадор от золотистого ретривера?','generate','helpful','dog_comparison'),
 ('Как устроен томатный куст?','generate','helpful','tomato_plant'),
 ('Что такое вулкан?','generate','helpful','volcano'),
 ('Что такое Млечный Путь?','generate','helpful','milky_way'),
 ('Что такое пончик?','retrieve','helpful',None),
])
def test_plans(text,strategy,priority,template):
    plan=MultimodalResponsePlanner().plan(text)
    assert plan.visual_needed and plan.visual_strategy==strategy and plan.visual_priority==priority and plan.template==template

def test_no_everyday_or_unsafe_auto_visual():
    planner=MultimodalResponsePlanner()
    for text in ['Привет','Спасибо','Как дела?','Объясни кратер Луны только голосом']:
        assert not planner.plan(text).visual_needed
    assert not planner.plan('Что такое ядовитое растение?',route=SimpleNamespace(tool='verification',quality={'consequence_risk':3})).visual_needed
    assert not MultimodalResponsePlanner(PresentationPolicy(auto_visual_for_helpful_topics=False)).plan('Что такое кратер Луны?').visual_needed
    timer=planner.plan('Поставь таймер на пять минут',route=SimpleNamespace(tool='timer',quality={}))
    assert timer.origin=='structured' and timer.visual_type=='timer'

def test_generated_templates_and_device_projection(settings):
    from gobot.presentation import esp32_projection
    async def run():
        service=Service(settings)
        for text in ['Что такое кратер Луны?','Какое расстояние до Луны?','Что такое солнечное затмение?','Что такое вулкан?','Как устроен томатный куст?','Чем отличается бычье сердце от обычных помидоров?','Что такое Млечный Путь?','Чем отличается лабрадор от золотистого ретривера?']:
            req=ChatRequest(text=text,mode='mock',remember=False)
            result=await service.visual.attachment(req,service.presentation_planner.plan(text))
            assert result.frame.images and result.frame.metadata.synthetic
            assert result.frame.metadata.backend=='local_procedural'
            compact=esp32_projection(result.frame)
            assert compact['payload']['image']['width']==240
            assert compact['payload']['template']==result.frame.metadata.template
            assert compact['payload']['synthetic'] and compact['payload']['credit']['license']
            data,_=service.visual.cache.read(result.frame.images[0].asset_id,'device');assert len(data)<65536
    asyncio.run(run())

def test_answer_and_first_audio_do_not_wait_for_visual(settings,monkeypatch):
    import gobot.brain as brain
    spoken=[]
    async def run():
        service=Service(settings);audio_started=asyncio.Event();attachment_done=asyncio.Event()
        original=service.visual.attachment
        async def attachment(*args,**kwargs):
            await audio_started.wait();result=await original(*args,**kwargs);attachment_done.set();return result
        async def stream(*args):
            yield 'Лунный кратер — это углубление на поверхности Луны.'
            await asyncio.sleep(.01)
        class Voice:
            async def synthesize(self,text,*a,**kw):
                assert not attachment_done.is_set();spoken.append(text);audio_started.set();yield b'\0\0'*20,24000
        monkeypatch.setattr(brain,'agent_status',lambda *_:{'antigravity':{'available':True}})
        monkeypatch.setattr(brain,'bridge_stream',stream);monkeypatch.setattr(service.visual,'attachment',attachment)
        req=ChatRequest(text='Что такое кратер Луны?',mode='auto',remember=False)
        events=await asyncio.wait_for(collect(voiced_events(service,Voice(),req)),2)
        assert any(e['type']=='visual_response' for e in events)
        assert events[-1]['type']=='final' and events[-1]['data']['provider']=='bridge:antigravity'
        assert events[-1]['data']['text']=='Лунный кратер — это углубление на поверхности Луны.'
        assert spoken==['Лунный кратер — это углубление на поверхности Луны.']
    asyncio.run(run())

async def collect(iterator):return [item async for item in iterator]

def test_visual_failure_does_not_fail_text_and_cancel_cleans_up():
    async def run():
        async def text():yield 'Ответ'
        async def fail():raise ValueError('fixture')
        events=await collect(merge_presentation(text(),asyncio.create_task(fail()),asyncio.Event()))
        assert ('text','Ответ') in events and ('visual_failed',None) in events
        closed=asyncio.Event();flag=asyncio.Event()
        async def slow():
            try:await asyncio.Event().wait()
            finally:closed.set()
        task=asyncio.create_task(slow());await asyncio.sleep(0)
        iterator=merge_presentation(text(),task,flag)
        await anext(iterator);flag.set()
        with pytest.raises(asyncio.CancelledError):await anext(iterator)
        assert closed.is_set() and task.cancelled()
    asyncio.run(run())

def test_tts_finishes_before_optional_visual(settings,monkeypatch):
    from contextlib import asynccontextmanager
    import gobot.brain as brain
    async def run():
        service=Service(settings);voice_closed=asyncio.Event();original=service.visual.attachment
        class Voice:
            @asynccontextmanager
            async def turn(self):
                try:yield self
                finally:voice_closed.set()
            async def synthesize(self,*a,**kw):yield b'\0\0'*20,24000
        async def attachment(*args,**kwargs):
            await voice_closed.wait();return await original(*args,**kwargs)
        async def answer(*args):yield 'Лунный кратер — углубление.'
        monkeypatch.setattr(brain,'agent_status',lambda *_:{'antigravity':{'available':True}})
        monkeypatch.setattr(brain,'bridge_stream',answer);monkeypatch.setattr(service.visual,'attachment',attachment)
        req=ChatRequest(text='Что такое кратер Луны?',mode='auto',remember=False)
        events=await asyncio.wait_for(collect(voiced_events(service,Voice(),req)),2)
        assert voice_closed.is_set() and any(e['type']=='visual_response' for e in events)
        stop=next(i for i,e in enumerate(events) if e['type']=='audio_stop')
        visual=next(i for i,e in enumerate(events) if e['type']=='visual_response')
        assert stop<visual
    asyncio.run(run())
