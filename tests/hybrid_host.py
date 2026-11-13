"""Real production API/gateway on a fixture DB. Paid provider boundary is denied."""
import asyncio,json
from pathlib import Path
import httpx
from fastapi import FastAPI,Request,HTTPException
from gobot.brain import Service
from gobot.config import Settings
from gobot.realtime import RealtimeManager
from gobot.realtime_budget import RealtimeBudget
from gobot.owner_testing import OwnerTestPolicy
from gobot.live import LiveManager
from gobot.audio import Speech
from gobot.family import Family
from gobot.family_access import IdentityAccessManager
from gobot.hybrid_api import attach_brain_hybrid
from gobot.device_store import DeviceStore
from hybrid_fixtures import weather_response,NOW

def setup_host(root):
    settings=Settings(db=str(root/'test.sqlite'),api_token='a'*48,bridge_secret='b'*48)
    brain=Service(settings);principal='browser-100-120-201-115';peer='100.120.201.115'
    profile=brain.configuration.devices.profile(principal+'@'+peer)
    brain.configuration.devices.update(principal+'@'+peer,{'weather':{'enabled':True,'location_name':'Лиссабон · fixture','latitude':38.72,'longitude':-9.14}})
    brain.configuration.weather.transport=httpx.MockTransport(weather_response);brain.configuration.weather.clock=lambda:NOW
    budget=RealtimeBudget(root/'realtime')
    rt=RealtimeManager(brain,budget=budget,identity=IdentityAccessManager(Family(brain.memory)))
    rt.owner_testing.policy_path.write_text(OwnerTestPolicy(enabled=True,authorization='fixture',allowed_client_id=profile.client_id,live_enabled=True).model_dump_json())
    live=LiveManager(rt);rt.live=live
    policy=root/'preview.json';policy.write_text('{"enabled":true,"fixture_mode":true}')
    backend=FastAPI()
    async def auth(request:Request):
        if request.headers.get('authorization')!='Bearer '+settings.api_token:raise HTTPException(401,'authentication_required')
    attach_brain_hybrid(backend,brain,rt,live,Speech(),auth,policy_path=policy)
    return {'settings':settings,'brain':brain,'realtime':rt,'live':live,'backend':backend,'policy':policy,
        'scope':{'principal':principal,'client_id':profile.client_id,'binding':profile.client_id,'profile_epoch':None},
        'auth':{'Authorization':'Bearer '+settings.api_token},'paid_calls':[],'http_paths':[]}

def block_paid(monkeypatch,host):
    async def deny(*a,**kw):host['paid_calls'].append('blocked_provider_call');raise AssertionError('paid egress is forbidden')
    async def deny_audio(*a,**kw):host['paid_calls'].append('blocked_tts');raise AssertionError('paid TTS forbidden');yield b'',24000
    from gobot.realtime_provider import RealtimeProvider
    from gobot.live_provider import LiveProvider
    from gobot.live_backend import LiveBackend
    from gobot.stt import OpenAIRecognition
    for cls,name in [(RealtimeProvider,'create'),(LiveProvider,'create'),(LiveBackend,'answer'),(OpenAIRecognition,'file')]:monkeypatch.setattr(cls,name,deny)
    monkeypatch.setattr(Speech,'synthesize',deny_audio)

def browser_host(monkeypatch,host):
    from gobot.browser import create_browser_app,ORIGIN
    real_client=httpx.AsyncClient
    async def transport(request):
        host['http_paths'].append(request.url.path)
        if request.url.host!='127.0.0.1' or request.url.port!=18781:
            host['paid_calls'].append('blocked_external_http');raise AssertionError('external request forbidden')
        async with real_client(transport=httpx.ASGITransport(app=host['backend']),base_url='http://127.0.0.1:18781') as client:
            return await client.request(request.method,request.url.path,params=request.url.params,headers=request.headers,content=request.content)
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:real_client(transport=kw.get('transport') or httpx.MockTransport(transport),**{k:v for k,v in kw.items() if k!='transport'}))
    gateway=create_browser_app(host['settings'])
    class LocalTestPeer:
        async def __call__(self,scope,receive,send):
            if scope['type']!='http':return await gateway(scope,receive,send)
            # Fixture host only: simulate the already authorized private peer and Origin.
            scope=dict(scope);scope['client']=('100.120.201.115',12345)
            headers=[(k,v) for k,v in scope['headers'] if k not in {b'host',b'origin'}]
            headers.append((b'host',b'plan.tailffc57c.ts.net:18786'))
            if scope['method']!='GET':headers.append((b'origin',ORIGIN.encode()))
            scope['headers']=headers
            await gateway(scope,receive,send)
    return LocalTestPeer()
