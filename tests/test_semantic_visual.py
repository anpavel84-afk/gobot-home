import asyncio,json,time
from pathlib import Path
from types import SimpleNamespace
import pytest
from gobot import brain
from gobot.models import ChatRequest
from gobot.memory import Memory
from gobot.visual_prefetch import extract_entity,planned_entity,SpeculativePhoto
from gobot.response_composer import VisualResponseComposer
from gobot.context_manager import ContextManager,serialize_context
from test_speculative_visuals import photo

CASES=json.loads((Path(__file__).parent/'data/semantic_visual_cases.json').read_text(encoding='utf8'))['cases']

@pytest.mark.parametrize('case',CASES,ids=[c['question'] for c in CASES])
def test_public_noun_phrases_do_not_depend_on_dictionary(case,monkeypatch):
    from gobot import image_query
    monkeypatch.setattr(image_query,'installed_entries',lambda:{})
    result=extract_entity(case['question'])
    assert (result.query if result else None)==case['entity']

def test_need_and_resolution_are_independent_and_smalltalk_stays_local():
    composer=VisualResponseComposer()
    req=ChatRequest(text='А расскажи еще что-нибудь',mode='auto')
    plan=composer.plan(req)
    assert plan.visual_needed and not plan.visual_query and plan.subject_resolution_method=='awaiting_early_answer'
    assert not composer.plan(req.model_copy(update={'text':'Привет, ГоБот!'})).visual_needed
    assert not composer.answer_visual_eligible(req.model_copy(update={'text':'Покажи пароль аккаунта'}))

def test_deferred_subject_uses_early_answer_and_does_not_wait_for_final():
    async def run():
        req=ChatRequest(text='Расскажи интересное',remember=False)
        calls=[]
        async def lookup(req,plan,**kw):calls.append(plan.visual_query);return photo(req,plan)
        worker=SpeculativePhoto(req,None,lookup,1)
        worker.observe('Северное сияние возникает в верхней атмосфере.')
        result=await asyncio.wait_for(worker.task,1)
        assert result.frame.images and calls==['северное сияние']
        assert worker.diagnostics['subject_resolution_method']=='early_answer_noun_phrase'
        await worker.close()
    asyncio.run(run())

def test_visual_context_is_confirmed_scoped_expiring_and_deleted(settings):
    memory=Memory(settings.db)
    req=ChatRequest(text='Что такое чёрная дыра?',mode='auto',device_id='personal:alice',profile_epoch='one')
    memory.start(req)
    trace=[{'visual_decision':{'subject_confirmed':True,'visual_subject':'черная дыра','subject_resolution_method':'request_noun_phrase'}}]
    memory.finish(req,'completed','Чёрная дыра искривляет пространство.','bridge:antigravity',trace)
    follow=ChatRequest(text='А расскажи ещё что-нибудь',mode='auto',device_id=req.device_id,
                       conversation_id=req.conversation_id,profile_epoch='one')
    memory.start(follow);ctx=memory.context(follow)
    assert planned_entity(follow.text,VisualResponseComposer().plan(follow,context=ctx),ctx).query=='черная дыра'
    packet=ContextManager().pack(follow.text,ctx,'FAST_CHAT')
    assert packet['active_visual_subject']['subject']=='черная дыра'
    assert 'active_visual_subject' not in serialize_context(follow.text,packet)
    assert memory.context(follow.model_copy(update={'profile_epoch':'two'}))['active_visual_subject'] is None
    assert memory.context(follow.model_copy(update={'device_id':'personal:bob'}))['active_visual_subject'] is None
    restored=Memory(settings.db)
    assert restored.context(follow)['active_visual_subject']
    with memory.connect() as c:c.execute('UPDATE active_visual_subjects SET expires=0')
    assert memory.context(follow)['active_visual_subject'] is None
    memory.finish(follow,'cancelled','','bridge:antigravity',[])
    memory.purge(conversation=req.conversation_id)
    with memory.connect() as c:assert not c.execute('SELECT * FROM active_visual_subjects').fetchall()

def test_two_forensic_questions_search_before_answer_and_keep_topic(settings,monkeypatch):
    async def run():
        service=brain.Service(settings);calls=[];release=asyncio.Event()
        async def lookup(req,plan,**kwargs):calls.append((req.text,plan.visual_query));return photo(req,plan)
        async def provider(settings,req,ctx):
            await asyncio.sleep(0)
            yield 'Чёрная дыра — область пространства с сильным притяжением. '
            await release.wait()
            yield 'Если хочешь, потом поговорим об истории.'
        monkeypatch.setattr(service.visual,'attachment',lookup)
        monkeypatch.setattr(brain,'bridge_stream',provider)
        monkeypatch.setattr(brain,'agent_status',lambda *_:{'antigravity':{'available':True}})
        req=ChatRequest(text='Что такое чёрная дыра?',mode='auto',usage_consent=True)
        for text in [req.text,'А расскажи еще что-нибудь.']:
            req=req.model_copy(update={'text':text,'turn_id':str(time.time_ns())})
            release.clear();await service.prepare(req);events=[]
            async with asyncio.timeout(3):
                async for e in service.events(req):
                    events.append(e)
                    if e.type=='visual_response':release.set()
            assert events[-1].type=='final'
            visual=next(e for e in events if e.type=='visual_response')
            assert events.index(visual)<next(i for i,e in enumerate(events) if e.type=='text_delta' and 'поговорим' in e.data['text'])
            diag=next(t['visual_decision'] for t in events[-1].data['trace'] if 'visual_decision' in t)
            assert diag['retrieval_started'] and diag['candidate_ready'] and diag['scene_sent']
            assert diag['scene_presented']=='unavailable'
            assert diag['visual_subject']=='черная дыра'
            assert not any(e.type=='screen_scene' and e.data['scene']['visual_subject']=='История' for e in events)
        assert [q for _,q in calls]==['черная дыра']*2
    asyncio.run(run())

def test_cancel_stops_pending_image_and_clears_visual_context(settings,monkeypatch):
    async def run():
        service=brain.Service(settings);closed=asyncio.Event()
        async def lookup(*args,**kw):
            try:await asyncio.Future()
            finally:closed.set()
        async def provider(*args):yield 'Чёрная дыра искривляет пространство. ';await asyncio.Future()
        monkeypatch.setattr(service.visual,'attachment',lookup)
        monkeypatch.setattr(brain,'bridge_stream',provider)
        monkeypatch.setattr(brain,'agent_status',lambda *_:{'antigravity':{'available':True}})
        req=ChatRequest(text='Что такое чёрная дыра?',mode='auto');await service.prepare(req)
        events=[]
        async with asyncio.timeout(3):
            async for e in service.events(req):
                events.append(e)
                if e.type=='text_delta':service.running[req.turn_id].set()
        assert closed.is_set() and not any(e.type=='visual_response' for e in events)
        with service.memory.connect() as c:assert not c.execute('SELECT * FROM active_visual_subjects').fetchall()
    asyncio.run(run())


def test_cancel_racing_completion_cannot_restore_subject(settings):
    memory=Memory(settings.db)
    req=ChatRequest(text='Что такое чёрная дыра?',mode='auto')
    trace=[{'visual_decision':{'subject_confirmed':True,'visual_subject':'черная дыра','subject_resolution_method':'request_noun_phrase'}}]
    memory.start(req);memory.clear_visual_turn(req.turn_id)
    memory.finish(req,'completed','Чёрная дыра.','bridge:antigravity',trace)
    with memory.connect() as c:assert not c.execute('SELECT * FROM active_visual_subjects').fetchall()
    later=ChatRequest(text='А расскажи ещё',mode='auto',conversation_id=req.conversation_id)
    memory.start(later);memory.finish(later,'completed','Чёрная дыра.','bridge:antigravity',trace)
    memory.clear_visual_turn(req.turn_id)
    with memory.connect() as c:assert c.execute('SELECT turn_id FROM active_visual_subjects').fetchone()[0]==later.turn_id
