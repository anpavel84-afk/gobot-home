"""Image fulfillment acceptance. Synthetic transports/assets; no paid API/CLI/audio."""
import asyncio,json
import pytest
from gobot.presentation import PresentationDecision
from gobot.visual_prefetch import extract_entity,TwoStageVisual
from gobot.visual import VisualService
from gobot.device_contract import ScreenPreferences
from gobot.models import ChatRequest
from test_two_stage_visual import result,until
from test_realtime_native import configured,start,command

@pytest.mark.parametrize('query,subject',[
    ('С какой скоростью летает орёл?','орел'),
    ('С какой скоростью орёл летает?','орел'),
    ('При какой температуре растёт бамбук?','бамбук'),
    ('На какой высоте летает самолёт?','самолет'),
    ('Покажи орла','орел'),('Покажи картинку орла','орел'),
    ('Как выглядит орёл?','орел'),('Найди фото орла','орел'),
    ('Сгенерируй мне орла','орел'),('Покажи кратер Луны','кратер луны'),
    ('Покажи изображение северного сияния','северное сияние'),
    ('Нарисуй картинку орла','орел'),
])
def test_grammatical_subject_is_not_measurement_or_media_noun(query,subject):
    assert extract_entity(query).query==subject

@pytest.mark.parametrize('query',['Покажи орла','Покажи картинку орла','Как выглядит орёл?','Найди фото орла','Сгенерируй мне орла','Покажи кратер Луны'])
def test_explicit_intent_has_real_source_first_plan(query):
    from gobot.response_composer import VisualResponseComposer
    intent=PresentationDecision().detect(query)
    plan=VisualResponseComposer().plan(ChatRequest(text=query))
    assert intent.kind=='image' and plan.origin=='explicit' and plan.visual_strategy=='retrieve'

def flow(query,fetch,publish,**prefs):
    from gobot.response_composer import VisualResponseComposer
    req=ChatRequest(text=query,mode='auto',screen_preferences=ScreenPreferences(**prefs))
    return TwoStageVisual(req,extract_entity(query),VisualResponseComposer().plan(req),fetch,publish)

@pytest.mark.parametrize('query',['С какой скоростью летает орёл?','Покажи орла','Покажи кратер Луны'])
def test_actual_asset_arrives_before_full_answer_and_without_generation(query):
    async def run():
        calls=[];published=[]
        async def fetch(req,plan,**kw):calls.append((plan.visual_query,req.screen_preferences.generation_allowed));return result(plan.visual_query)
        async def publish(r,*args):published.append(r)
        worker=flow(query,fetch,publish)
        try:
            await until(lambda:published)
            assert published[0].frame.images and worker.diagnostics['asset_delivered'] and not worker.final
            assert calls==[(extract_entity(query).query,False)]
        finally:await worker.close()
    asyncio.run(run())

@pytest.mark.parametrize('query',['С какой скоростью летает орёл?','Покажи орла','Покажи кратер Луны'])
def test_missing_photo_becomes_recoverable_card_not_successful_badge(query):
    async def run():
        published=[]
        async def fetch(req,plan,**kw):return result(plan.visual_query,missing=True)
        async def publish(r,*args):published.append(r)
        worker=flow(query,fetch,publish)
        try:
            await until(lambda:published)
            card=published[0].frame
            assert not card.images and card.metadata.state=='unavailable'
            assert card.metadata.facts['generation_fallback_reason']=='image_generation_disabled'
            assert 'Генерация' in card.text and 'повторить' in card.text
            assert not worker.diagnostics['candidate_ready'] and not worker.diagnostics['asset_delivered']
            assert worker.diagnostics['fulfillment_state']=='fallback'
        finally:await worker.close()
    asyncio.run(run())

def test_explicit_generation_fallback_does_not_wait_for_model_to_claim_capability():
    async def run():
        calls=[];published=[]
        async def fetch(req,plan,**kw):
            enabled=req.screen_preferences.generation_allowed;calls.append(enabled)
            return result(plan.visual_query,missing=not enabled)
        async def publish(r,*args):published.append(r)
        worker=flow('Сгенерируй мне орла',fetch,publish,generation_allowed=True,generation_mode='missing',generation_consent=True,generation_daily_limit=1)
        try:
            await until(lambda:published)
            assert calls==[False,True] and published[-1].frame.images and worker.generation_attempted
            worker.observe('Я не могу показывать картинки.',final=True)
            await asyncio.wait_for(worker.task,2)
            assert calls==[False,True]
        finally:await worker.close()
    asyncio.run(run())

@pytest.mark.parametrize('prefs,code',[
    ({},'image_generation_disabled'),
    ({'generation_allowed':True},'image_generation_mode_off'),
    ({'generation_allowed':True,'generation_mode':'missing'},'image_generation_consent_required'),
    ({'generation_allowed':True,'generation_mode':'missing','generation_consent':True},'image_generation_daily_limit'),
    ({'visual_source_policy':'wikimedia_only'},'image_generation_source_policy'),
])
def test_exact_generation_policy_reason(prefs,code):
    assert VisualService.generation_blocker(ChatRequest(text='Покажи орла',screen_preferences=ScreenPreferences(**prefs)))==code

def test_dictionary_proper_names_do_not_hide_single_common_sense():
    from gobot.image_query import ImageQueryPlanner
    planner=ImageQueryPlanner({'орел':{'senses':[['Aquila'],['Oryol'],['eagle']]},'луна':{'senses':[['Luna'],['moon']]},'кратер':{'senses':[['crater']]},'лук':{'senses':[['onion'],['bow']]}})
    assert planner.plan('орел').terms[0]=='eagle' and not planner.plan('орел').ambiguous
    assert planner.plan('кратер луны').terms[0]=='crater moon'
    assert planner.plan('лук').ambiguous # Multiple common senses still require resolution.

@pytest.mark.parametrize('query,title,expected',[
    ('кратер Луны','Лунный кратер',True),('двигатель автомобиля','Автомобильный двигатель',True),
    # Irregular/unparsed derivations are not guessed by this conservative rule.
    ('сердце человека','Человеческое сердце',False),('кольца Сатурна','Сатурновы кольца',False),
    ('кратер Луны','Кратер',False),('кратер Луны','Лунный вулкан',False),
    ('нервная система человека','Нервная система животных',False),
])
def test_article_grammar_preserves_head_and_qualifiers(query,title,expected):
    from gobot.visual_images import article_title_matches
    assert bool(article_title_matches(query,title)) is expected

def test_source_exception_publishes_fallback_frame_not_just_status():
    async def run():
        published=[]
        async def fetch(*a,**kw):raise RuntimeError('Synthetic outage, never copy raw exception')
        async def publish(r,*args):published.append(r)
        worker=flow('Покажи орла',fetch,publish)
        try:
            await until(lambda:published)
            assert published[0].frame.metadata.reason=='image_source_unavailable'
            assert 'Synthetic' not in published[0].frame.text and not worker.diagnostics['asset_delivered']
        finally:await worker.close()
    asyncio.run(run())

def test_native_explicit_tool_joins_one_worker_and_waits_for_actual_delivery(tmp_path,settings):
    async def run():
        m,p,b=configured(tmp_path,settings);calls=[]
        async def fetch(req,plan,**kw):calls.append(plan.visual_query);return result(plan.visual_query)
        m.brain.visual.attachment=fetch;s=await start(m)
        try:
            turn=await s.new_turn(query='Покажи орла')
            await s.tool('call_visual','visual_request',json.dumps({'query':turn.query}),turn)
            output=next(json.loads(e['item']['output']) for e in s.ws.sent if e.get('item',{}).get('call_id')=='call_visual')
            assert calls==['орел'] and output['asset_delivered'] and not output['presented']
            assert 'visual_request' in {tool['name'] for tool in s.config['tools']}
            await command(s,'visual_presented',frame_id='foreign-frame',turn_id=turn.id)
            assert not turn.visual_outcome['presented']
            await command(s,'visual_presented',frame_id=output['frame_id'],turn_id=turn.id)
            assert turn.visual_outcome['presented']
            await command(s,'visual_failed',frame_id=output['frame_id'],turn_id=turn.id)
            assert turn.visual_outcome['status']=='delivery_failed' and not turn.visual_outcome['presented']
            assert next(e for e in reversed(s.events) if e['type']=='visual_response')['data']['presentation']['metadata']['reason']=='image_delivery_failed'
            assert calls==['орел'] and len(p.creations)==1
            await command(s,'visual_presented',frame_id=output['frame_id'],turn_id=turn.id)
            assert turn.visual_outcome['status']=='delivery_failed' # A late decode acknowledgement cannot undo the failure.
        finally:await m.shutdown()
    asyncio.run(run())

def test_native_policy_disabled_generation_explained_without_denial_of_wikimedia(tmp_path,settings):
    async def run():
        m,p,b=configured(tmp_path,settings);calls=[]
        async def fetch(req,plan,**kw):calls.append(plan.visual_query);return result(plan.visual_query,missing=True)
        m.brain.visual.attachment=fetch;s=await start(m)
        try:
            turn=await s.new_turn(query='Покажи орла')
            await s.tool('call_blocked','visual_request',json.dumps({'query':turn.query}),turn)
            output=next(json.loads(e['item']['output']) for e in s.ws.sent if e.get('item',{}).get('call_id')=='call_blocked')
            assert output['status']=='fallback' and not output['asset_delivered']
            assert output['generation_blocked_reason']=='image_generation_policy_denied' and output['source_failure_reason']=='image_not_found'
            assert 'политика' in output['message'] and calls==['орел'] and not s.closed
        finally:await m.shutdown()
    asyncio.run(run())

def test_late_asr_tool_waits_and_cannot_replace_question_with_unrelated_subject(tmp_path,settings):
    async def run():
        m,p,b=configured(tmp_path,settings);calls=[]
        async def fetch(req,plan,**kw):calls.append(plan.visual_query);return result(plan.visual_query)
        m.brain.visual.attachment=fetch;s=await start(m)
        try:
            turn=await s.new_turn('input-late')
            tool=asyncio.create_task(s.tool('call_late','visual_request',json.dumps({'query':'Покажи орла'}),turn))
            await asyncio.sleep(.02);assert not calls
            await s.input_text(turn,'Покажи орла');await tool
            assert calls==['орел']
            await s.tool('call_paraphrase','gobot_tool',json.dumps({'query':'Найди фотографию орла'}),turn)
            joined=next(json.loads(e['item']['output']) for e in s.ws.sent if e.get('item',{}).get('call_id')=='call_paraphrase')
            assert joined['asset_delivered'] and calls==['орел']
            await s.tool('call_wrong','visual_request',json.dumps({'query':'Покажи личный пароль'}),turn)
            output=next(json.loads(e['item']['output']) for e in s.ws.sent if e.get('item',{}).get('call_id')=='call_wrong')
            assert output['error']=='explicit_visual_request_required' and calls==['орел']
        finally:await m.shutdown()
    asyncio.run(run())

def test_explicit_request_is_independent_of_automatic_accompaniment_settings(tmp_path,settings):
    from gobot.device_contract import DeviceProfile
    async def run():
        m,p,b=configured(tmp_path,settings);calls=[]
        async def profile(_):return DeviceProfile(screen=ScreenPreferences(automatic_illustrations=False,style='minimal',visual_strategy='answer_only'))
        m.profile_loader=profile
        async def fetch(req,plan,**kw):calls.append(plan.visual_query);return result(plan.visual_query)
        m.brain.visual.attachment=fetch;s=await start(m)
        try:
            ordinary=await s.new_turn(query='С какой скоростью летает орёл?')
            await asyncio.wait_for(ordinary.visual_ready.wait(),1);assert not calls
            explicit=await s.new_turn(query='Покажи орла')
            await s.tool('call_explicit_minimal','visual_request',json.dumps({'query':explicit.query}),explicit)
            assert calls==['орел'] and explicit.visual_outcome['asset_delivered']
        finally:await m.shutdown()
    asyncio.run(run())
