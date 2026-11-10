"""Public synthetic subjects, fake media/providers only. No image or LLM expenses."""
import asyncio,io
from dataclasses import replace
import pytest
from PIL import Image
from gobot.device_contract import ScreenPreferences
from gobot.models import ChatRequest
from gobot.presentation import VisualIntent
from gobot.presentation_planner import ResponsePresentationPlan
from gobot.response_composer import VisualResponseComposer
from gobot.visual import VisualService
from gobot.visual_images import ImageCache,ImageCandidate
from gobot.image_generation import OpenAIImageGenerationAdapter

def bitmap(size=(480,480)):
    out=io.BytesIO();Image.new('RGB',size,'orange').save(out,'JPEG');return out.getvalue()

def candidate(subject='Moon',**kw):
    return ImageCandidate('https://upload.wikimedia.org/wikipedia/commons/a/ab/fixture.jpg',subject,
        'https://commons.wikimedia.org/wiki/File:fixture.jpg','Synthetic author','CC BY 4.0',
        'https://creativecommons.org/licenses/by/4.0/',**kw)

class Provider:
    def __init__(self,name,events,items=(),raw=None):
        self.name=name;self.events=events;self.items=items;self.raw=raw or bitmap();self.client=self
    async def page_images(self,q,n):self.events.append((self.name,'page',q));return self.items
    async def search(self,q,n):self.events.append((self.name,'search',q));return self.items
    async def get(self,url):self.events.append((self.name,'download'));return self.raw,'image/jpeg'

def service(tmp_path,wiki,secondary):
    return VisualService(ImageCache(tmp_path/'images'),config_loader=lambda:{'provider':'openverse','user_agent':'Fixture'},
        provider_factory=lambda cfg:wiki if cfg['provider']=='wikimedia' else secondary,fallback_factory=lambda:wiki)

def request(subject='Moon',**preferences):
    pref=ScreenPreferences(**{'generation_allowed':True,'generation_consent':True,'generation_mode':'missing',
        'generation_provider':'openai','generation_daily_limit':2,**preferences})
    return ChatRequest(text='Расскажи про '+subject,remember=False,screen_preferences=pref)

def plan(subject='Moon'):
    return ResponsePresentationPlan(visual_needed=True,visual_strategy='retrieve',visual_query=subject,subject_label=subject)

@pytest.mark.parametrize('subject',['Moon','Oxheart tomato','Falcon 9 rocket'])
def test_wikimedia_success_skips_secondary_and_generation_and_reuses_cache(tmp_path,monkeypatch,subject):
    async def run():
        events=[];wiki=Provider('wiki',events,[candidate(subject,matched_query=subject)])
        secondary=Provider('secondary',events);v=service(tmp_path,wiki,secondary)
        async def forbidden(*a,**k):raise AssertionError('Generation must not run on retrieval success')
        monkeypatch.setattr(OpenAIImageGenerationAdapter,'generate',forbidden)
        req=request(subject);one=await v.attachment(req,plan(subject));count=len(events)
        two=await v.attachment(req,plan(subject))
        assert one.frame.images and one.frame.metadata.backend=='wikimedia'
        assert two.frame.metadata.cache_hit and len(events)==count
        assert not any(e[0]=='secondary' for e in events)
        raw,_=v.cache.read(one.frame.images[0].asset_id,'device')
        assert Image.open(io.BytesIO(raw)).size==(240,240)
    asyncio.run(run())

@pytest.mark.parametrize('bad,raw',[
    ([],None),([candidate('Orange flower')],None),([candidate('Moon placeholder icon')],None),
    ([candidate()],bitmap((30,30))),([candidate()],b'broken jpeg'),
])
def test_only_missing_or_unusable_wikimedia_enters_controlled_generation(tmp_path,monkeypatch,bad,raw):
    async def run():
        events=[];v=service(tmp_path,Provider('wiki',events,bad,raw),Provider('secondary',events))
        async def generate(self,prompt,**kw):
            assert kw['consent'] and any(e[0]=='wiki' for e in events)
            events.append(('generate',prompt));return bitmap((1024,1024)),{'total_tokens':12}
        monkeypatch.setattr(OpenAIImageGenerationAdapter,'generate',generate)
        req=request();one=await v.attachment(req,plan());two=await v.attachment(req,plan())
        assert one.frame.images and one.frame.metadata.synthetic and one.frame.metadata.backend=='openai_image_api'
        assert two.frame.metadata.cache_hit and len([e for e in events if e[0]=='generate'])==1
        assert not any(e[0]=='secondary' for e in events)
        assert one.frame.metadata.facts['retrieval_fallback_reason']
        assert v.generation_usage(req.device_id)['statuses']=={'completed':1}
        with v.cache.connect() as c:
            row=c.execute('SELECT model,prompt,status,usage,asset_id FROM generation_lineage').fetchone()
            assert 'Moon' in row['prompt'] and row['asset_id']==one.frame.images[0].asset_id
        for variant in ['browser','device']:
            data,_=v.cache.read(one.frame.images[0].asset_id,variant)
            assert Image.open(io.BytesIO(data)).size==((1024,1024) if variant=='browser' else (240,240))
    asyncio.run(run())

@pytest.mark.parametrize('preferences',[{'visual_source_policy':'wikimedia_only'}, {'generation_consent':False}, {'generation_daily_limit':0}])
def test_policy_or_budget_denial_keeps_voice_path_unaffected(tmp_path,monkeypatch,preferences):
    async def run():
        events=[];v=service(tmp_path,Provider('wiki',events),Provider('secondary',events))
        async def forbidden(*a,**k):raise AssertionError('Paid call forbidden')
        monkeypatch.setattr(OpenAIImageGenerationAdapter,'generate',forbidden)
        result=await v.attachment(request(**preferences),plan())
        assert not result.frame.images and result.frame.metadata.state=='unavailable'
        assert v.generation_usage('synthetic')['attempts']=={}
    asyncio.run(run())

def test_optional_secondary_runs_only_after_wikimedia_failure(tmp_path):
    async def run():
        events=[];v=service(tmp_path,Provider('wiki',events),Provider('secondary',events,[candidate()]))
        result=await v.attachment(request(visual_source_policy='wikimedia_first'),plan())
        assert result.frame.images and events[0][0]=='wiki'
        assert any(e[0]=='secondary' for e in events)
    asyncio.run(run())

def test_real_subject_does_not_skip_retrieval_for_illustration_preference():
    req=request('северное сияние',source_preference='illustrations',generation_mode='helpful')
    assert VisualResponseComposer().plan(req).visual_strategy=='retrieve'

def test_cancelled_generation_is_reserved_once_and_never_automatically_retried(tmp_path,monkeypatch):
    async def run():
        events=[];v=service(tmp_path,Provider('wiki',events),Provider('secondary',events));started=asyncio.Event();calls=[]
        async def generate(self,prompt,**kw):
            calls.append(prompt);started.set();await asyncio.Event().wait()
        monkeypatch.setattr(OpenAIImageGenerationAdapter,'generate',generate)
        task=asyncio.create_task(v.attachment(request(),plan()))
        await asyncio.wait_for(started.wait(),2)
        # The image worker is pending independently; other event-loop work is not blocked.
        useful_voice_event=asyncio.Event();useful_voice_event.set();await useful_voice_event.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
        again=await v.attachment(request(),plan())
        assert not again.frame.images and len(calls)==1
        assert v.generation_usage(request().device_id)['statuses']=={'cancelled_unknown':1}
    asyncio.run(run())

def test_medical_followup_subject_never_enters_unvalidated_generation(tmp_path,monkeypatch):
    async def run():
        events=[];v=service(tmp_path,Provider('wiki',events),Provider('secondary',events))
        async def forbidden(*a,**k):raise AssertionError('Medical synthetic anatomy blocked')
        monkeypatch.setattr(OpenAIImageGenerationAdapter,'generate',forbidden)
        result=await v.generated(request('ещё подробнее'),plan('human heart'))
        assert not result.frame.images and result.frame.metadata.reason=='verified_diagram_required'
    asyncio.run(run())

def test_generation_provider_failure_is_nonfatal_and_not_automatically_retried(tmp_path,monkeypatch):
    async def run():
        events=[];v=service(tmp_path,Provider('wiki',events),Provider('secondary',events));calls=[]
        async def failed(self,prompt,**kw):calls.append(prompt);raise RuntimeError('Synthetic provider outage')
        monkeypatch.setattr(OpenAIImageGenerationAdapter,'generate',failed)
        one=await v.attachment(request(),plan());two=await v.attachment(request(),plan())
        assert not one.frame.images and not two.frame.images and len(calls)==1
        assert one.frame.metadata.facts['generation_fallback_reason']=='generation_provider_unavailable'
        assert v.generation_usage(request().device_id)['statuses']=={'failed_unknown':1}
    asyncio.run(run())

def test_creative_dragon_uses_existing_generation_strategy_when_explicitly_allowed():
    req=request('сказочного дракона');req.text='Придумай сказочного дракона'
    chosen=VisualResponseComposer().plan(req)
    assert chosen.visual_strategy=='generate' and chosen.reason=='ai_illustration'

def test_new_native_guest_session_does_not_reset_generation_daily_budget(tmp_path,monkeypatch):
    async def run():
        events=[];v=service(tmp_path,Provider('wiki',events),Provider('secondary',events));calls=[]
        async def generate(self,prompt,**kw):calls.append(prompt);return bitmap(),{'total_tokens':10}
        monkeypatch.setattr(OpenAIImageGenerationAdapter,'generate',generate)
        one=request(generation_daily_limit=1).model_copy(update={'device_id':'realtime-guest:one','client_id':'stable-client'})
        two=request(generation_daily_limit=1).model_copy(update={'device_id':'realtime-guest:two','client_id':'stable-client'})
        assert (await v.generated(one,plan())).frame.images
        same=await v.generated(two,plan())
        assert same.frame.images and same.frame.metadata.cache_hit
        different=await v.generated(two,plan('Different public subject'))
        assert not different.frame.images and len(calls)==1
        assert v.generation_usage('visual-device:stable-client')['attempts']=={'openai':1}
    asyncio.run(run())
