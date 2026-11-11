"""Fixed-origin GPT-Live WebRTC creation and trusted sideband. No implicit retries."""
import asyncio,json,re
from urllib.parse import quote
import httpx
from websockets.asyncio.client import connect
from .secrets_store import load_openai_key
from .live_contract import live_sdp

class LiveProvider:
    def __init__(self,key_loader=load_openai_key,client_factory=None,connector=connect):
        self.key_loader=key_loader;self.client_factory=client_factory or (lambda:httpx.AsyncClient(trust_env=False,timeout=20,follow_redirects=False));self.connector=connector
    def headers(self):
        key=self.key_loader()
        if not key:raise RuntimeError('openai_key_missing')
        return {'Authorization':'Bearer '+key}
    @staticmethod
    def ident(value):
        if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,256}',value):raise ValueError('invalid_live_provider_id')
        return quote(value,safe='')
    async def create(self,sdp,config):
        live_sdp(sdp)
        async with asyncio.timeout(20),self.client_factory() as c:
            r=await c.post('https://api.openai.com/v1/live/sessions',headers=self.headers(),json={'session':config,'transport':{'type':'webrtc','sdp':sdp}})
        if r.status_code!=201:
            try:error=r.json().get('error',{})
            except ValueError:error={}
            self.last_rejection={k:v for k,v in error.items() if k in {'code','type','param'} and (v is None or isinstance(v,str) and re.fullmatch(r'[A-Za-z0-9_.\[\]-]{0,160}',v))}
            raise RuntimeError('live_create_rejected_'+str(r.status_code))
        try:value=r.json();ident=value['session']['id'];self.ident(ident)
        except (ValueError,KeyError,TypeError):raise RuntimeError('live_provider_id_missing') from None
        # Preserve ID before SDP validation so a malformed answer can still be closed.
        return ident,value.get('transport',{}).get('sdp','')
    def attach(self,ident):
        return self.connector('wss://api.openai.com/v1/live/sessions/'+self.ident(ident)+'/attach',
            additional_headers=self.headers(),proxy=None,max_size=1048576,open_timeout=10,close_timeout=2)
    async def cleanup(self,ident):
        # Documented bounded sideband cleanup for WebRTC, not the SIP-only hangup assumption.
        async with self.attach(ident) as ws:
            await ws.send(json.dumps({'type':'session.close','event_id':'cleanup-close'}))
            import asyncio
            async with asyncio.timeout(8):
                async for raw in ws:
                    event=json.loads(raw)
                    if event.get('type')=='session.closed':return event
        raise RuntimeError('live_finalization_unconfirmed')
