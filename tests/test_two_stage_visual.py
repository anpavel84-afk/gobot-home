"""Shared scheduling/alignment fixtures, never provider calls or acoustic acceptance."""
import asyncio,hashlib
import pytest
from gobot.models import ChatRequest
from gobot.device_contract import ScreenPreferences
from gobot.presentation import Presentation,VisualMetadata,VisualImage,VisualSource,esp32_projection
from gobot.presentation_planner import ResponsePresentationPlan
from gobot.visual import VisualResult
from gobot.visual_prefetch import TwoStageVisual,extract_entity,answer_entity,stable_visual_chunk

def result(subject,*,missing=False):
    ident=hashlib.sha256(subject.encode()).hexdigest();base='/api/visual/assets/'+ident
    images=[] if missing else [VisualImage(asset_id=ident,url=base+'/browser.jpg',preview_variant=base+'/preview.jpg',device_variant=base+'/device.jpg',
        caption=subject,alt=subject,width=480,height=320,source=VisualSource(label='Wikimedia Commons',url='https://commons.wikimedia.org/wiki/File:Fixture.jpg'),
        attribution='Synthetic test fixture',license='Public domain')]
    frame=Presentation(id=ident,type='info_card' if missing else 'image_card',title=subject,images=images,
        metadata=VisualMetadata(state='unavailable' if missing else 'ready',reason='image_not_found' if missing else None))
    return VisualResult(frame,'','')

async def until(predicate):
    for _ in range(100):
        if predicate():return
        await asyncio.sleep(.003)
    assert predicate()

def setup(query,**preferences):
    req=ChatRequest(text=query,screen_preferences=ScreenPreferences(**preferences))
    entity=extract_entity(query);plan=entity.plan() if entity else ResponsePresentationPlan()
    return req,entity,plan

@pytest.mark.parametrize('query,answer,subject',[
    ('Какие самые опасные пауки в Бразилии?','Самые опасные пауки относятся к роду Phoneutria.','Phoneutria'),
    ('Что такое кратер Луны?','Лунный кратер — это углубление. Например, кратер Тихо хорошо виден с Земли.','кратер Тихо'),
    ('Расскажи про сердце человека','Сердце человека обеспечивает кровообращение и перекачивает кровь.','Кровообращение человека'),
    ('Что такое чёрная дыра?','Чёрная дыра — это область пространства, откуда свет не выходит.','черная дыра'),
    ('Расскажи про попугаев','Солнечная аратинга — яркий попугай из Южной Америки.','солнечная аратинга'),
])
def test_question_then_stable_answer_refines_only_bound_subject(query,answer,subject):
    async def run():
        req,entity,plan=setup(query);published=[];calls=[]
        async def fetch(req,plan,**kw):calls.append(plan.visual_query);return result(plan.visual_query)
        async def publish(r,stage,revision):published.append((r,stage,revision))
        flow=TwoStageVisual(req,entity,plan,fetch,publish)
        await until(lambda:published)
        assert published[0][1:]==(1,0) and not flow.final
        flow.observe(answer)
        await until(lambda:flow.state.answer_topic is not None)
        flow.finish();await asyncio.wait_for(flow.task,2)
        assert flow.state.answer_topic.query==subject
        assert published[-1][0].frame.title==subject
        assert len(published)<=3 and flow.revision<=2
        if subject==entity.query:assert len(calls)==1 and len(published)==1
        if subject=='Кровообращение человека':assert published[-1][0].frame.metadata.image_fit=='contain'
        for r,stage,revision in published:
            compact=esp32_projection(r.frame)['payload']
            assert compact['visual_stage']==('provisional' if stage==1 else 'refined')
            assert compact['visual_revision']==revision
    asyncio.run(run())

def test_mismatch_cancels_refinement_and_never_generates():
    async def run():
        req,entity,plan=setup('Какой самый ядовитый паук?',generation_allowed=True,generation_consent=True,generation_mode='missing',generation_daily_limit=3)
        published=[];calls=[];warnings=[]
        async def fetch(req,plan,**kw):calls.append((plan.visual_query,req.screen_preferences.generation_allowed));return result(plan.visual_query)
        async def publish(r,stage,revision):published.append((stage,revision))
        flow=TwoStageVisual(req,entity,plan,fetch,publish,on_mismatch=lambda:warnings.append(True))
        await until(lambda:published)
        flow.observe('Самым ядовитым плодом называют опасное растение.',final=True)
        await asyncio.wait_for(flow.task,2)
        assert flow.state.topic_alignment_status=='mismatch' and warnings==[True]
        assert published==[(1,0)] and calls==[('Пауки',False)]
    asyncio.run(run())

@pytest.mark.parametrize('missing,consent',[(False,True),(True,False),(True,True)])
def test_generation_only_missing_aligned_once_with_consent(missing,consent):
    async def run():
        req,entity,plan=setup('Что такое северное сияние?',generation_allowed=consent,generation_consent=consent,generation_mode='missing',generation_daily_limit=2)
        calls=[];published=[]
        async def fetch(req,plan,**kw):
            paid=req.screen_preferences.generation_allowed;calls.append(paid)
            return result(plan.visual_query,missing=missing and not paid)
        async def publish(r,stage,revision):published.append((stage,revision))
        flow=TwoStageVisual(req,entity,plan,fetch,publish)
        await until(lambda:flow.initial_done)
        assert calls==[False] # Never spend on an unconfirmed question-side guess.
        flow.observe('Северное сияние — свечение верхних слоёв атмосферы.',final=True)
        await asyncio.wait_for(flow.task,2)
        assert calls==([False,True] if missing and consent else [False])
    asyncio.run(run())

@pytest.mark.parametrize('mode,stages',[('question_only',[1]),('answer_only',[2]),('question_then_refine',[1,2])])
def test_strategy_is_persistable_and_answer_only_waits(mode,stages):
    async def run():
        req,entity,plan=setup('Расскажи про пауков',visual_strategy=mode);published=[]
        async def fetch(req,plan,**kw):return result(plan.visual_query)
        async def publish(r,stage,revision):published.append(stage)
        flow=TwoStageVisual(req,entity,plan,fetch,publish)
        await asyncio.sleep(.01)
        assert bool(published)==(mode!='answer_only')
        flow.observe('Опасные пауки относятся к роду Phoneutria.',final=True)
        await asyncio.wait_for(flow.task,2);assert published==stages
    asyncio.run(run())

def test_weak_or_unrelated_words_do_not_change_scene_or_generate():
    async def run():
        req,entity,plan=setup('Расскажи про пауков');published=[];calls=[]
        async def fetch(req,plan,**kw):calls.append(plan.visual_query);return result(plan.visual_query)
        async def publish(r,stage,revision):published.append(stage)
        flow=TwoStageVisual(req,entity,plan,fetch,publish)
        await until(lambda:published)
        flow.observe('Пауки ловят насекомых и обитают в разных странах. Хочешь, могу рассказать про историю Бразилии?',final=True)
        await asyncio.wait_for(flow.task,2);assert published==[1] and calls==['Пауки']
    asyncio.run(run())

def test_cancelled_turn_cannot_publish_late_result_or_restart():
    async def run():
        req,entity,plan=setup('Расскажи про пауков');entered=asyncio.Event();published=[]
        async def fetch(req,plan,**kw):entered.set();await asyncio.sleep(60)
        async def publish(*args):published.append(args)
        flow=TwoStageVisual(req,entity,plan,fetch,publish)
        await entered.wait();await flow.close();flow.observe('Опасные пауки относятся к роду Phoneutria.',final=True)
        await asyncio.sleep(.01);assert not published and not flow.workers
    asyncio.run(run())

def test_chunk_does_not_treat_partial_or_two_words_as_meaning():
    assert not stable_visual_chunk('Пауки Phoneu')
    assert not stable_visual_chunk('Пауки бывают')
    assert stable_visual_chunk('Пауки относятся к роду Phoneutria. Следующее предложение')=='Пауки относятся к роду Phoneutria. '
    assert answer_entity(extract_entity('Расскажи про пауков'),'Расскажи про пауков','Могу рассказать про растения и про Phoneutria.')[0]=='unknown'

def test_slow_provisional_cannot_overwrite_ready_refinement_and_updates_are_bounded():
    async def run():
        req,entity,plan=setup('Расскажи про пауков');release=asyncio.Event();published=[]
        async def fetch(req,plan,**kw):
            if plan.visual_query=='Пауки':await release.wait()
            return result(plan.visual_query)
        async def publish(r,stage,revision):published.append((r.frame.title,stage,revision))
        flow=TwoStageVisual(req,entity,plan,fetch,publish)
        flow.observe('Опасные пауки относятся к роду Phoneutria.')
        await until(lambda:published)
        release.set();await asyncio.sleep(.01)
        assert published==[('Phoneutria',2,1)]
        # New stable fragments cannot cause unlimited lookups or a carousel.
        for genus in ['Loxosceles','Latrodectus','Atrax','Missulena']:
            flow.observe('Опасные пауки относятся к роду '+genus+'.')
            await asyncio.sleep(.01)
        flow.finish();await asyncio.wait_for(flow.task,2)
        assert flow.revision==2 and len(published)<=2
    asyncio.run(run())
