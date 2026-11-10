"""Installed into upstream core/providers/llm/gobot/gobot.py by prepare_upstream.py."""
import json,uuid
import httpx
from core.providers.llm.base import LLMProviderBase
class LLMProvider(LLMProviderBase):
    def __init__(self,config):
        self.url=config['brain_url'];self.token=config['brain_token'];self.device_id=config.get('device_id','voice-provisioned')
        if not self.url.startswith('http://127.0.0.1:'):raise ValueError('Brain must be local')
    def response(self,session_id,dialogue,**kwargs):
        # Upstream LLM generator runs in its connection executor. No nested event loop.
        text=next((m.get('content','') for m in reversed(dialogue) if m.get('role')=='user'),'')
        body={'text':text,'device_id':self.device_id,'conversation_id':str(session_id),'turn_id':str(uuid.uuid4())}
        with httpx.Client(trust_env=False,timeout=httpx.Timeout(20,connect=2)) as client:
            with client.stream('POST',self.url+'/api/v1/chat/stream',headers={'Authorization':'Bearer '+self.token},json=body) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if line.startswith('data: '):
                        obj=json.loads(line[6:])
                        if obj['type']=='text_delta':yield obj['data']['text']
                        elif obj['type'] in {'error','cancelled'}:return
