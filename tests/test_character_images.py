import asyncio
from unittest.mock import patch
from gobot import brain
from gobot.character_images import characters
from gobot.models import ChatRequest
from test_speculative_visuals import photo

TEXT=('Первый герой — динозавр Герти, созданная Уинзором Маккеем. '
      'В мультфильме Фантасмагория появляется человечек Фантош. '
      'Ещё один герой — кот Феликс.')

def test_character_names_exclude_authors():
    entities=list(characters(TEXT))
    assert [e.label for e in entities]==['Динозавр Герти','Фантош — Фантасмагория','Кот Феликс']
    assert all('Макке' not in e.query for e in entities)

def test_three_streaming_images_before_final(settings,monkeypatch):
    async def run():
        service=brain.Service(settings);first=asyncio.Event();calls=[]
        async def fetch(req,plan,**kw):
            calls.append(plan.visual_query);return photo(req,plan)
        async def provider(*args):
            yield TEXT.split('. ')[0]+'. '
            await first.wait()
            yield '. '.join(TEXT.split('. ')[1:])
        monkeypatch.setattr(service.visual,'attachment',fetch)
        monkeypatch.setattr(brain,'bridge_stream',provider)
        monkeypatch.setattr(brain,'agent_status',lambda *_:{'antigravity':{'available':True}})
        req=ChatRequest(text='Кто был первым мультипликационным героем?',mode='auto',remember=True)
        await service.prepare(req);frames=[]
        async with asyncio.timeout(3):
            async for item in service.events(req):
                if item.type=='visual_response':frames.append(item.data['presentation']);first.set()
        assert len(frames)==3 and len(calls)==3
        assert all(f['metadata']['backend']!='answer_map' for f in frames)
        history=await service.history(req.conversation_id,req.device_id)
        assert len(history['messages'][-1]['presentations'])==3
    asyncio.run(run())

def test_cancel_stops_character_fetch(settings,monkeypatch):
    async def run():
        service=brain.Service(settings);started=asyncio.Event();closed=asyncio.Event()
        async def fetch(*args,**kwargs):
            started.set()
            try:await asyncio.Event().wait()
            finally:closed.set()
        async def provider(*args):
            yield 'Первый герой — динозавр Герти. '
            await asyncio.Event().wait()
        monkeypatch.setattr(service.visual,'attachment',fetch)
        monkeypatch.setattr(brain,'bridge_stream',provider)
        monkeypatch.setattr(brain,'agent_status',lambda *_:{'antigravity':{'available':True}})
        req=ChatRequest(text='Расскажи о первом мультперсонаже',mode='auto',remember=False)
        async def consume():return [e async for e in service.events(req)]
        task=asyncio.create_task(consume())
        await asyncio.wait_for(started.wait(),2);service.running[req.turn_id].set()
        events=await asyncio.wait_for(task,2)
        assert closed.is_set() and not any(e.type=='visual_response' for e in events)
    asyncio.run(run())
