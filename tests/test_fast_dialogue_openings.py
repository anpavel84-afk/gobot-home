import asyncio,json,wave,time,io
from pathlib import Path
import pytest
from gobot import brain
from gobot.models import ChatRequest
from gobot.pipeline import voiced_events
from gobot.conversation_control import closing_intent
from gobot.speech_openings import OpeningCache,catalog
from gobot.quick_intents import match_quick,library

@pytest.mark.parametrize('mode',['auto','fast','codex'])
def test_no_thanks_is_silent_local_and_does_not_start_cli_or_tts(settings,monkeypatch,mode):
    async def run():
        service=brain.Service(settings)
        monkeypatch.setattr(brain,'agent_status',lambda *_:(_ for _ in ()).throw(AssertionError('CLI admission must not run')))
        class Speech:
            async def synthesize(self,*a,**k):raise AssertionError('No paid synthesis');yield
        req=ChatRequest(text='Нет, спасибо!',mode=mode,remember=False)
        items=[e async for e in voiced_events(service,Speech(),req,paid_tts_consent=True)]
        assert items[-1]['type']=='final' and items[-1]['data']['provider']=='local'
        assert any(e['type']=='tool_status' and e['data'].get('status')=='conversation_ended' for e in items)
        assert not any(e['type'] in {'audio_chunk','sentence_ready'} for e in items)
    asyncio.run(run())

def test_closing_is_anchored_and_pending_is_not_permission():
    context={'messages':[{'role':'assistant','content':'Хочешь узнать ещё что-нибудь?'}]}
    assert closing_intent('Нет.',context)
    assert closing_intent('Спасибо',context)
    for text in ['Нет, спасибо, а сколько времени?','Да, спасибо','Не говори «нет спасибо»','Что означает нет спасибо?']:
        assert closing_intent(text,context) is None
    assert closing_intent('Нет',{'pending_action':{'expires':time.time()+60,'kind':'home'}})=='decline_pending'
    assert closing_intent('Да',{'pending_action':{'expires':time.time()+60}}) is None

def test_unsupported_compound_duration_and_additional_command_never_become_shorter_timer():
    from gobot.timer_duration import timer_seconds
    assert timer_seconds('Засеки сто пять минут') is None
    assert timer_seconds('Поставь таймер на три минуты и расскажи стих') is None

def test_opening_catalog_cache_voice_integrity_and_context(tmp_path):
    rows=catalog();assert len(rows)==100 and sum(len(r['text']) for r in rows)==2886
    cache=OpeningCache(tmp_path)
    assert cache.status('marin')['ready_count']==0
    ident=rows[0]['id'];cache.put('marin',ident,b'\x01\0'*2400,24000,rows[0]['text'])
    assert cache.clip('marin',ident) and cache.clip('cedar',ident) is None
    chosen=cache.select('Дай ответ','marin',{},'fixture')
    assert chosen['text']==rows[0]['text'] and 'path' not in chosen
    path=cache.clip('marin',ident)['path'];path.write_bytes(b'broken')
    assert cache.clip('marin',ident) is None

def test_cached_opening_is_in_main_context_but_never_answer_or_tts(settings,monkeypatch,tmp_path):
    async def run():
        service=brain.Service(settings);service.openings=OpeningCache(tmp_path)
        row=next(r for r in catalog() if r['category']=='explanation')
        service.openings.put('marin',row['id'],b'\x01\0'*2400,24000,row['text'])
        captured=[];spoken=[]
        async def model(settings,req,context):captured.append(context);yield 'Краткое объяснение.'
        class Voice:
            async def synthesize(self,text,*a,**kw):spoken.append(text);yield b'\1\0',24000
        monkeypatch.setattr(brain,'agent_status',lambda *_:{'antigravity':{'available':True}})
        monkeypatch.setattr(brain,'bridge_stream',model)
        req=ChatRequest(text='Объясни гравитацию',mode='fast',remember=False)
        items=[e async for e in voiced_events(service,Voice(),req,paid_tts_consent=True)]
        assert any(e['type']=='tool_status' and e['data'].get('status')=='speech_opening_ready' for e in items)
        assert captured[0]['speech_opening']['text']==row['text']
        assert spoken==['Краткое объяснение.']
        assert row['text'] not in items[-1]['data']['text']
    asyncio.run(run())

SAMPLES=[(row['intent'],text) for row in library()['entries'] if row['patterns'] for text in row['examples']]
@pytest.mark.parametrize('intent,text',SAMPLES)
def test_quick_library_examples_have_one_validated_intent(intent,text):
    assert match_quick(text).intent==intent
    assert match_quick('ГоБот, '+text).intent==intent

@pytest.mark.parametrize('text',['Не ставь таймер на 5 минут','Расскажи, как поставить таймер','Если поставить таймер на 3 минуты, что будет?','Таймер или будильник?'])
def test_explanations_negations_and_ambiguity_do_not_execute(text):
    assert match_quick(text) is None

def test_clock_and_timer_are_real_local_tools(settings,monkeypatch):
    async def run():
        service=brain.Service(settings)
        monkeypatch.setattr(brain,'agent_status',lambda *_:(_ for _ in ()).throw(AssertionError('No CLI for known commands')))
        for text in ['Сколько сейчас времени?','Какая сегодня дата?','Засеки три минуты','Сколько осталось на таймере?']:
            req=ChatRequest(text=text,mode='auto',remember=False)
            events=[e async for e in service.events(req)]
            assert events[-1].type=='final',events
            assert events[-1].data['provider']=='local'
            assert events[-1].data['verification']['accepted']
    asyncio.run(run())

QUICK_CASES=json.loads((Path(__file__).parent/'data/quick-utterance-evaluation.json').read_text(encoding='utf8'))['cases']
@pytest.mark.parametrize('case',QUICK_CASES)
def test_quick_utterance_dataset(case):
    result=match_quick(case['text'])
    assert (result.intent if result else None)==case['expected_intent']
    if 'seconds' in case:assert result.slots['seconds']==case['seconds']
