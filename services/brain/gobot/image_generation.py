"""Image-only providers. Every paid attempt requires a saved limit and consent."""
import asyncio
import base64
import json
import httpx
from .secrets_store import load_openai_key,openai_key_present
from .visual_images import ImageUnavailable,MAX_DOWNLOAD

MODEL='gpt-image-2.6-flare'

class CodexImageGenerationAdapter:
    @staticmethod
    def status():
        return {'provider':'codex','billing_kind':'cli_subscription','available':False,
                'provider_capability_detected':True,'reason':'image_only_isolation_not_verified',
                'cli_version_checked':'0.159.2','real_generation_tested':False}
    async def generate(self,*args,**kwargs):
        raise ImageUnavailable('image_only_isolation_not_verified')

class OpenAIImageGenerationAdapter:
    def __init__(self,*,key_loader=load_openai_key,transport=None):
        self.key_loader=key_loader;self.transport=transport
    @staticmethod
    def status():
        return {'provider':'openai','model':MODEL,'billing_kind':'api',
                'available':openai_key_present(),'real_generation_tested':False,
                'reason':'requires_image_api_consent_and_limit'}
    async def generate(self,prompt,*,consent=False):
        if not consent:raise ImageUnavailable('image_generation_consent_required')
        key=await asyncio.to_thread(self.key_loader)
        if not key:raise ImageUnavailable('openai_image_key_missing')
        async with httpx.AsyncClient(trust_env=False,transport=self.transport,timeout=120) as client:
            async with client.stream('POST','https://api.openai.com/v1/images/generations',
                headers={'Authorization':'Bearer '+key},
                json={'model':MODEL,'prompt':prompt,'n':1,'size':'1024x1024','quality':'low','output_format':'jpeg'}) as response:
                if response.status_code!=200:raise ImageUnavailable('openai_image_request_failed')
                raw=bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw)>MAX_DOWNLOAD*2:raise ImageUnavailable('image_generation_response_too_large')
        try:
            value=json.loads(raw);encoded=value['data'][0]['b64_json']
            data=base64.b64decode(encoded,validate=True)
            if len(data)>MAX_DOWNLOAD:raise ValueError()
        except (ValueError,KeyError,IndexError,TypeError):raise ImageUnavailable('invalid_generated_image') from None
        return data,{k:v for k,v in value.get('usage',{}).items() if isinstance(v,int) and v>=0}

def generation_status():
    return {'codex':CodexImageGenerationAdapter.status(),'openai':OpenAIImageGenerationAdapter.status(),
            'paid_generation_default':'off'}
