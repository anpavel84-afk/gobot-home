"""Fixed-origin OpenAI Realtime transport. No retries of call creation or turns."""
import json,re,hashlib
import httpx
from websockets.asyncio.client import connect
from .realtime_contract import audio_only_sdp

class RealtimeProviderError(RuntimeError): pass

class RealtimeProvider:
    def __init__(self, key_loader=None, client_factory=None, connector=None):
        from .secrets_store import load_openai_key
        self.key_loader=key_loader or load_openai_key
        self.client_factory=client_factory or (lambda:httpx.AsyncClient(trust_env=False,timeout=15,follow_redirects=False))
        self.connector=connector or connect

    def headers(self):
        key=self.key_loader()
        if not key:raise RealtimeProviderError('openai_key_missing')
        return {'Authorization':'Bearer '+key}

    async def create(self,sdp,config,owner):
        audio_only_sdp(sdp)
        try:
            async with self.client_factory() as client:
                r=await client.post('https://api.openai.com/v1/realtime/calls',
                    headers={**self.headers(),'OpenAI-Safety-Identifier':hashlib.sha256(owner.encode()).hexdigest()},
                    files={'sdp':(None,sdp,'application/sdp'),'session':(None,json.dumps(config),'application/json')})
            if r.status_code!=201:raise RealtimeProviderError('realtime_call_rejected')
            location=r.headers.get('location','')
            match=re.fullmatch(r'(?:https://api\.openai\.com)?/v1/realtime/calls/(rtc_[A-Za-z0-9_-]{1,180})',location)
            if not match:raise RealtimeProviderError('realtime_call_id_missing')
            # Return the ID before parsing the answer, so invalid SDP can also be hung up.
            return match[1],r.text
        except httpx.HTTPError:raise RealtimeProviderError('realtime_network_error') from None

    def attach(self,call_id):
        if not re.fullmatch(r'rtc_[A-Za-z0-9_-]{1,180}',call_id):raise ValueError('invalid_call_id')
        return self.connector('wss://api.openai.com/v1/realtime?call_id='+call_id,
                              additional_headers=self.headers(),proxy=None,max_size=1048576,open_timeout=10,close_timeout=2)

    async def hangup(self,call_id):
        if not re.fullmatch(r'rtc_[A-Za-z0-9_-]{1,180}',call_id):raise ValueError('invalid_call_id')
        try:
            async with self.client_factory() as client:
                r=await client.post('https://api.openai.com/v1/realtime/calls/'+call_id+'/hangup',headers=self.headers())
                if r.status_code not in {200,204,404,410}:raise RealtimeProviderError('realtime_hangup_unconfirmed')
        except httpx.HTTPError:raise RealtimeProviderError('realtime_hangup_unconfirmed') from None
