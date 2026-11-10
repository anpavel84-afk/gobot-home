import asyncio,base64,json
from contextlib import asynccontextmanager
import pytest
from gobot.audio import Speech
from gobot.processes import AgentError
from gobot.brain import Service
from gobot.models import ChatRequest
from gobot.pipeline import voiced_events

def transport(opened,sent,closed,ready=None):
    class WS:
        def __init__(self):self.queue=asyncio.Queue()
        async def send(self,raw):
            event=json.loads(raw);sent.append(event)
            if event['type']=='session.update':
                await self.queue.put({'type':'session.updated'})
                if ready:ready.set()
            if event['type']=='response.create':
                await self.queue.put({'type':'response.output_audio.delta','delta':base64.b64encode(b'\0\0'*10).decode()})
                await self.queue.put({'type':'response.done','response':{'status':'completed'}})
        async def recv(self):return json.dumps(await self.queue.get())
    @asynccontextmanager
    async def connect(*args,**kwargs):
        opened.append(True)
        try:yield WS()
        finally:closed.append(True)
    return connect

def test_reuse_only_inside_turn_and_no_accumulating_history():
    opened=[];sent=[];closed=[]
    async def run():
        speech=Speech(api_key='fixture',connector=transport(opened,sent,closed))
        async with speech.turn() as turn:
            await turn.prepare('openai','marin',paid_consent=True)
            assert len(opened)==1 and [e['type'] for e in sent]==['session.update']
            for text in ['Десятого ноября.','Пятнадцатого ноября.']:
                assert [part async for part in turn.synthesize(text,paid_consent=True)]==[(b'\0\0'*10,24000)]
        assert len(opened)==len(closed)==1
        creates=[e['response'] for e in sent if e['type']=='response.create']
        assert len(creates)==2 and all(e['conversation']=='none' and e['tools']==[] for e in creates)
        assert creates[1]['input'][0]['content'][0]['text']=='Пятнадцатого ноября.'
        async with speech.turn() as turn:
            assert [part async for part in turn.synthesize('Другой запрос.',paid_consent=True)]
        assert len(opened)==len(closed)==2
    asyncio.run(run())

def test_turn_cancel_and_consent_gate():
    opened=[];sent=[];closed=[]
    async def run():
        speech=Speech(api_key='fixture',connector=transport(opened,sent,closed))
        async with speech.turn() as turn:
            with pytest.raises(AgentError,match='consent_required'):await turn.prepare('openai','marin')
            assert not opened
            stream=turn.synthesize('Не закончено.',paid_consent=True)
            await anext(stream);await stream.aclose()
            assert sent[-1]['type']=='response.cancel' and not turn.busy
        assert closed
    asyncio.run(run())

def test_preparation_overlaps_answer_without_generating_placeholder(settings,monkeypatch):
    import gobot.brain as brain
    async def run():
        opened=[];sent=[];closed=[];ready=asyncio.Event()
        speech=Speech(api_key='fixture',connector=transport(opened,sent,closed,ready))
        async def answer(*args):
            await asyncio.wait_for(ready.wait(),1)
            assert not [e for e in sent if e['type']=='response.create']
            yield 'Сегодня 10 ноября. '
            yield 'Праздник будет 15 ноября.'
        monkeypatch.setattr(brain,'fast_stream',answer)
        service=Service(settings);request=ChatRequest(text='Синтетический тест',remember=False)
        events=[e async for e in voiced_events(service,speech,request,paid_tts_consent=True)]
        assert events[-1]['type']=='final'
        inputs=[e['response']['input'][0]['content'][0]['text'] for e in sent if e['type']=='response.create']
        assert inputs==['Сегодня десятое ноября.','Праздник будет пятнадцатого ноября.']
        assert len(opened)==len(closed)==1
        assert events[-1]['data']['text']=='Сегодня 10 ноября. Праздник будет 15 ноября.'
    asyncio.run(run())

def test_status_counts_audio_after_text_has_finished(settings):
    async def run():
        service=Service(settings);req=ChatRequest(text='Привет',mode='mock',remember=False)
        class Voice:
            async def synthesize(self,*a,**k):
                yield b'\0\0',24000
                await asyncio.Event().wait()
        stream=voiced_events(service,Voice(),req)
        while (await anext(stream))['type']!='audio_chunk':pass
        assert service.active_voice_streams==1
        await stream.aclose();assert service.active_voice_streams==0
    asyncio.run(run())
