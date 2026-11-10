"""Structured plans from the main answer. Fixtures do not measure real model skill."""
import asyncio,io,json
from types import SimpleNamespace
from PIL import Image
import pytest
from gobot.models import ChatRequest
from gobot.response_composer import VisualResponseComposer
from gobot.visual_subject import OPEN,CLOSE,VisualDirective,VisualMarkupFilter,grounded
from gobot.visual_images import ImageCandidate,ImageCache
from gobot.visual import VisualService
from gobot.image_query import subject_matches_caption

QUESTION='Оранжевый попугай — это какая порода?'
FIRST='В примере упомянуты солнечные аратинги.'
TAIL=' У них яркое оперение.'
PLAN={'kind':'photo','domain':'animal','subject':'солнечные аратинги'}
BLOCK=OPEN+json.dumps(PLAN,ensure_ascii=False)+CLOSE


@pytest.mark.parametrize('size',[1,2,7,64,10000])
def test_metadata_never_reaches_display_or_tts_at_any_split(size):
    raw=FIRST+BLOCK+TAIL;parser=VisualMarkupFilter();events=[]
    for i in range(0,len(raw),size):events+=parser.feed(raw[i:i+size])
    events+=parser.feed('',final=True)
    assert ''.join(value for kind,value in events if kind=='text')==FIRST+TAIL
    assert [value.subject for kind,value in events if kind=='visual_plan']==['солнечные аратинги']


@pytest.mark.parametrize('body',[
    'not JSON',json.dumps({**PLAN,'url':'http://localhost/private'}),
    json.dumps({**PLAN,'subject':'https://example.com/key'}),'x'*5000,
])
def test_invalid_metadata_hidden_and_answer_kept(body):
    events=VisualMarkupFilter().feed(FIRST+OPEN+body+CLOSE+TAIL,final=True)
    assert ''.join(value for kind,value in events if kind=='text')==FIRST+TAIL
    assert all(kind!='visual_plan' for kind,value in events)


def test_unfinished_duplicate_and_bounded_blocks():
    parser=VisualMarkupFilter();events=parser.feed(FIRST+BLOCK+BLOCK+TAIL,final=True)
    assert sum(kind=='visual_plan' for kind,value in events)==1
    parser=VisualMarkupFilter();events=parser.feed(FIRST+OPEN+'{"subject":')
    events+=parser.feed('',final=True)
    assert ''.join(v for k,v in events if k=='text')==FIRST
    parser=VisualMarkupFilter();parser.feed(OPEN)
    for _ in range(100):parser.feed('x'*1000);assert len(parser.buffer)<=1024
    assert not parser.feed(CLOSE,final=True)


def test_semantic_choice_and_independent_rejection_rules():
    composer=VisualResponseComposer();req=ChatRequest(text=QUESTION,mode='auto')
    route=SimpleNamespace(tool=None,quality={});initial=composer.plan(req,route)
    directive=VisualDirective(**PLAN)
    plan=composer.plan_from_answer(req,FIRST,route,{},initial,directive)
    assert plan.visual_query=='солнечные аратинги' and plan.subject_source=='answer'
    assert not grounded(directive,QUESTION,'Это не солнечные аратинги.')
    assert not grounded(directive,QUESTION,'Здесь нет названия вида.')
    assert not grounded(directive,'Расскажи о моей птице',FIRST)
    wrong=VisualDirective(kind='photo',domain='plant',subject='цветовые мутации')
    assert not grounded(wrong,QUESTION,'У птиц бывают цветовые мутации.')
    substring=VisualDirective(kind='photo',domain='plant',subject='цвет')
    assert not grounded(substring,'Что это?', 'Здесь цветовые мутации.')


def test_color_words_are_not_plant_scenes():
    req=ChatRequest(text=QUESTION,mode='auto');composer=VisualResponseComposer()
    scene=composer.compose(req,answer='У попугаев встречаются цветовые мутации и оранжевый цвет.')
    assert scene.visual_subject=='Попугаи'
    other=composer.compose(ChatRequest(text='Почему так?',mode='auto'),answer='Цветовые мутации меняют цвет оперения.')
    assert other.visual_subject!='Растения'


@pytest.mark.parametrize('name',['солнечный аратинга','солнечной аратинги','солнечные аратинги'])
def test_inflected_species_phrase_preserves_semantics(name):
    from gobot.image_query import ImageQueryPlanner,canonical_subject
    assert ImageQueryPlanner().plan(name).terms[0]=='sun conure'
    assert subject_matches_caption(name,'Aratinga solstitialis, Sun conure')
    assert not subject_matches_caption(name,'Orange flower')
    assert canonical_subject(name) in {'солнечная аратинга','солнечные аратинги'}


def test_strict_subject_metadata_gate_and_cache(tmp_path):
    calls=[];downloads=[];raw=io.BytesIO();Image.new('RGB',(300,200),'orange').save(raw,'JPEG')
    class Provider:
        client=None
        def __init__(self):self.client=self
        async def search(self,query,limit):
            calls.append(query)
            return [ImageCandidate('https://api.openverse.org/v1/images/'+str(i)*8+'-1111-1111-1111-111111111111/thumb/',caption,'https://www.flickr.com/photos/example/'+str(i),'Fixture author','CC BY 4.0','https://creativecommons.org/licenses/by/4.0/') for i,caption in [(1,'Orange flower'),(2,'Sun conure — Aratinga solstitialis')]]
        async def get(self,url):downloads.append(url);return raw.getvalue(),'image/jpeg'
    async def run():
        service=VisualService(ImageCache(tmp_path/'cache'),provider_factory=lambda _:Provider(),config_loader=lambda:{'provider':'openverse'})
        req=ChatRequest(text=QUESTION,mode='auto',remember=False)
        composer=VisualResponseComposer();plan=composer.plan_from_answer(req,FIRST,directive=VisualDirective(**PLAN))
        first=await service.attachment(req,plan);second=await service.attachment(req,plan)
        assert len(first.frame.images)==1 and second.frame.metadata.cache_hit
        assert first.frame.images[0].caption.startswith('Sun conure')
        assert first.frame.metadata.facts['query_basis']=='answer_entity'
        device,_=service.cache.read(first.frame.images[0].asset_id,'device');assert len(device)<=65536
    asyncio.run(run());assert calls==['солнечные аратинги'] and len(downloads)==1
    assert subject_matches_caption('солнечные аратинги','Aratinga solstitialis')
    assert not subject_matches_caption('солнечные аратинги','Orange plant')


def test_existing_commons_fallback_after_primary_failure(tmp_path):
    from gobot.visual_images import ImageUnavailable
    calls=[];raw=io.BytesIO();Image.new('RGB',(240,240),'orange').save(raw,'JPEG')
    class Primary:
        async def search(self,*args):calls.append('primary');raise ImageUnavailable('image_network_unavailable')
    class Fallback:
        client=None
        def __init__(self):self.client=self
        async def search(self,query,limit):
            calls.append(query)
            return [ImageCandidate('https://upload.wikimedia.org/wikipedia/commons/a/ab/fixture.jpg','Aratinga solstitialis','https://commons.wikimedia.org/wiki/File:fixture.jpg','Fixture author','CC BY-SA 3.0','https://creativecommons.org/licenses/by-sa/3.0/')]
        async def get(self,*args):return raw.getvalue(),'image/jpeg'
    async def run():
        service=VisualService(ImageCache(tmp_path/'fallback'),provider_factory=lambda _:Primary(),
            fallback_factory=Fallback,config_loader=lambda:{'provider':'openverse'})
        plan=VisualResponseComposer().plan_from_answer(ChatRequest(text=QUESTION,mode='auto'),FIRST,directive=VisualDirective(**PLAN))
        result=await service.attachment(ChatRequest(text=QUESTION,mode='auto',remember=False),plan)
        assert result.frame.images and result.frame.metadata.backend=='wikimedia'
    asyncio.run(run());assert calls==['primary','sun conure']


@pytest.mark.parametrize('suffix,expected',[
    ('?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content=thumbnail',''),
    ('?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content=thumbnail_unscaled',''),
    ('?download=1','?download=1'),('?utm_campaign=unknown','?utm_campaign=unknown'),
])
def test_only_known_commons_tracking_fields_canonicalized(suffix,expected):
    from gobot.visual_images import CommonsImages
    url='https://thumb.wikimedia.org/wikipedia/commons/thumb/a/ab/bird.jpg/960px-bird.jpg'
    class Client:
        async def get(self,*a,**k):
            return json.dumps({'query':{'pages':{'1':{'imageinfo':[{'thumburl':url+suffix,
                'mime':'image/jpeg','descriptionurl':'https://commons.wikimedia.org/wiki/File:bird.jpg',
                'extmetadata':{'LicenseShortName':{'value':'CC BY-SA 3.0'},'LicenseUrl':{'value':'https://creativecommons.org/licenses/by-sa/3.0/'}}}]}}}}).encode(),'application/json'
    async def run():
        result=await CommonsImages(Client()).search('bird')
        assert result[0].url==url+expected
    asyncio.run(run())


@pytest.mark.parametrize('mode',['auto','codex'])
def test_plain_stream_refines_one_prefetch_without_blocking_voice(settings,monkeypatch,mode):
    import gobot.brain as module
    from gobot.brain import Service
    from gobot.pipeline import voiced_events
    async def run():
        service=Service(settings);audio=asyncio.Event();calls=[];plans=[];spoken=[]
        async def source(*args):
            calls.append(1)
            for fragment in [FIRST,BLOCK[:10],BLOCK[10:],TAIL]:yield fragment
        async def image(req,plan,**kw):
            plans.append(plan);await audio.wait()
            return service.visual.fallback(req,'Фото пока недоступно','fixture_no_network')
        class Voice:
            async def synthesize(self,text,*a,**kw):
                spoken.append(text);audio.set();yield b'\x01\x00'*20,24000
        monkeypatch.setattr(module,'agent_status',lambda *_:{'antigravity':{'available':True},'codex':{'available':True}})
        monkeypatch.setattr(module,'bridge_stream',source);monkeypatch.setattr(service.visual,'attachment',image)
        req=ChatRequest(text=QUESTION,mode=mode,remember=False)
        events=await asyncio.wait_for(_collect(voiced_events(service,Voice(),req)),2)
        final=next(e for e in events if e['type']=='final')
        assert final['data']['text']==FIRST+TAIL
        assert len(calls)==1 and [p.visual_query for p in plans]==['Попугаеобразные','солнечная аратинга']
        assert sum(e['type']=='visual_response' for e in events)==0
        assert all('gobot_visual' not in part for part in spoken)
        assert ''.join(spoken).replace(' ','')==(FIRST+TAIL).replace(' ','')
        assert not any(e['type']=='visual_response' for e in events)
    asyncio.run(run())


def test_cancelled_answer_cancels_pending_image(settings,monkeypatch):
    import gobot.brain as module
    from gobot.brain import Service
    async def run():
        service=Service(settings);began=asyncio.Event();closed=asyncio.Event()
        async def source(*args):
            yield FIRST+BLOCK
            await asyncio.Event().wait()
        async def image(*args,**kwargs):
            began.set()
            try:await asyncio.Event().wait()
            finally:closed.set()
        monkeypatch.setattr(module,'agent_status',lambda *_:{'antigravity':{'available':True}})
        monkeypatch.setattr(module,'bridge_stream',source);monkeypatch.setattr(service.visual,'attachment',image)
        req=ChatRequest(text=QUESTION,mode='auto',remember=False);await service.prepare(req)
        task=asyncio.create_task(_collect(service.events(req)));await asyncio.wait_for(began.wait(),1)
        service.running[req.turn_id].set();await asyncio.wait_for(task,1)
        assert closed.is_set() and req.turn_id not in service.running
    asyncio.run(run())


async def _collect(iterator):return [item async for item in iterator]
