import asyncio,base64,io
import httpx
from PIL import Image
from gobot.image_generation import OpenAIImageGenerationAdapter,CodexImageGenerationAdapter
from gobot.visual_images import ImageCache
from gobot.visual import VisualService
from gobot.models import ChatRequest
from gobot.device_contract import ScreenPreferences
from gobot.response_composer import VisualResponseComposer
from gobot.presentation_planner import ResponsePresentationPlan

def test_official_api_shape_and_consent_without_paid_call():
    raw=io.BytesIO();Image.new('RGB',(1024,1024),'blue').save(raw,'JPEG');calls=[]
    async def handler(request):
        calls.append(request)
        assert request.url.path=='/v1/images/generations'
        return httpx.Response(200,json={'data':[{'b64_json':base64.b64encode(raw.getvalue()).decode()}],'usage':{'total_tokens':12}})
    async def run():
        adapter=OpenAIImageGenerationAdapter(key_loader=lambda:'fixture',transport=httpx.MockTransport(handler))
        try:await adapter.generate('planet')
        except Exception as error:assert str(error)=='image_generation_consent_required'
        assert not calls
        data,usage=await adapter.generate('planet',consent=True)
        assert Image.open(io.BytesIO(data)).size==(1024,1024) and usage['total_tokens']==12
    asyncio.run(run())

def test_generation_limits_cache_and_anatomy_gate(tmp_path,monkeypatch):
    calls=[];raw=io.BytesIO();Image.new('RGB',(1024,1024),'blue').save(raw,'JPEG')
    async def generate(self,prompt,**kwargs):
        assert kwargs['consent'];calls.append(prompt);return raw.getvalue(),{'total_tokens':12}
    monkeypatch.setattr(OpenAIImageGenerationAdapter,'generate',generate)
    async def run():
        service=VisualService(ImageCache(tmp_path/'cache'))
        pref=ScreenPreferences(generation_allowed=True,generation_consent=True,generation_mode='helpful',
            generation_provider='openai',generation_daily_limit=1)
        req=ChatRequest(text='Придумай сказочную планету',screen_preferences=pref,remember=False)
        plan=VisualResponseComposer().plan(req)
        one,two=await asyncio.gather(service.generated(req,plan),service.generated(req,plan))
        assert one.frame.images and two.frame.images and len(calls)==1
        assert max(one.frame.images[0].width,two.frame.images[0].width)==1024
        assert one.frame.metadata.billing_kind=='api' and one.frame.metadata.synthetic
        other=plan.model_copy(update={'subject_label':'Другая планета'})
        denied=await service.generated(req,other)
        assert not denied.frame.images and denied.frame.metadata.reason=='image_generation_daily_limit'
        anatomy=await service.generated(req.model_copy(update={'text':'Как устроено сердце человека?'}),plan)
        assert not anatomy.frame.images and len(calls)==1
    asyncio.run(run())

def test_codex_capability_does_not_claim_ready_generation():
    state=CodexImageGenerationAdapter.status()
    assert state['provider_capability_detected'] and not state['available'] and not state['real_generation_tested']
