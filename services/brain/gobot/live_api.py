"""Authenticated C endpoints in the existing FastAPI services and private gateway."""
import asyncio,json,re
import httpx
from fastapi import Request,HTTPException,Depends
from fastapi.responses import JSONResponse,StreamingResponse
from pydantic import ValidationError
from .live_contract import LiveOffer,LiveCommand,LIVE_MODEL
from .realtime_api import bounded_json
from .models import ID

def valid_id(value):
    if not re.fullmatch(ID,value):raise HTTPException(422,'invalid_live_application_id')
    return value

def attach_brain_live(app,manager,auth):
    def owned(ident,scope):
        try:return manager.owned(ident,scope['device_id'],scope['client_id'],scope.get('profile_epoch') or None)
        except KeyError:raise HTTPException(404,'live_session_not_found')
    @app.get('/api/v1/live/status',dependencies=[Depends(auth)])
    async def status(binding:str=''):
        from .skill_catalogue import summary
        return {'engine':'gpt_live','requested_version':'1.1','actual_candidate_model':LIVE_MODEL,'version_1_1_verified':False,
            'enabled':manager.owner_testing.policy().live_enabled and (not binding or manager.owner_testing.authorized(binding)),'delegation':'client','store':False,
            'billing':manager.budget.status(),'active_sessions':sum(not s.closed for s in manager.sessions.values()),
            'default_changed':True,'product_default_engine':'live','conversation_modes':['live','legacy'],'idle_seconds':10,
            'input_action_bridge_version':3,'native_tools':['clock','timer','weather_current','weather_forecast','weather_setup','utility','skill_readiness'],'skill_catalogue':summary(),
            'wake_word_ready':False,'iphone_verified':False,'private_memory_ready':False,'silent_backend_llm':False,
            'general_backend_ready':manager.owner_testing.policy().live_backend_enabled,'general_backend_model':'gpt-6-luna',
            'general_backend_input_limit':2048,'general_backend_output_limit':512,'general_backend_concurrency':1}
    @app.post('/api/v1/live/sessions',dependencies=[Depends(auth)])
    async def create(request:Request):
        try:
            offer=LiveOffer.model_validate(await bounded_json(request))
            from .device_store import DeviceStore
            devices=DeviceStore(manager.brain.configuration.devices.root)
            scope=await asyncio.to_thread(devices.scoped_owner,offer.device_id,offer.client_id)
            profile=await asyncio.to_thread(devices.profile,scope)
            s,answer=await manager.start(offer,profile)
            return {'session_id':s.id,'sdp':answer,'model':LIVE_MODEL,'voice':s.config['audio']['output']['voice'],
                'configuration_confirmed':s.ready,'delegation':'client','store':False,'memory_mode':'guest_ram_only',
                'mode_conversation_id':s.mode_flow.id if s.mode_flow else None}
        except PermissionError as error:raise HTTPException(403,str(error))
        except (ValueError,ValidationError):raise HTTPException(409,'invalid_or_busy_live_session')
        except RuntimeError as error:
            code=str(error)
            if not re.fullmatch(r'live_create_rejected_[45]\d\d|live_settings_not_confirmed|live_invalid_answer_sdp|live_(?:previous_)?finalization_unconfirmed|live_setup_cancelled',code):code='live_setup_or_provider_admission_failed'
            raise HTTPException(502,code)
        except Exception:raise HTTPException(502,'live_setup_or_provider_admission_failed')
    @app.post('/api/v1/live/sessions/{ident}/command',dependencies=[Depends(auth)])
    async def command(ident:str,request:Request):
        valid_id(ident)
        body=await bounded_json(request,16000);scope={k:body.pop(k,None) for k in ['device_id','client_id','profile_epoch']}
        try:parsed=LiveCommand.model_validate(body)
        except ValidationError:raise HTTPException(422,'invalid_live_command')
        if ident not in manager.sessions and parsed.action=='end':
            await asyncio.to_thread(manager.budget.cancel_before_start,ident,[scope['device_id'],scope['client_id'],scope['profile_epoch']])
            return {'closed':True,'provider_started':False,'final_usage_confirmed':True}
        s=owned(ident,scope)
        try:return await s.command(parsed)
        except PermissionError:raise HTTPException(403,'live_operation_not_allowed')
        except ValueError:raise HTTPException(422,'invalid_live_command')
    @app.get('/api/v1/live/sessions/{ident}/events',dependencies=[Depends(auth)])
    async def events(ident:str,request:Request,device_id:str,client_id:str,profile_epoch:str=''):
        valid_id(ident)
        s=owned(ident,{'device_id':device_id,'client_id':client_id,'profile_epoch':profile_epoch})
        if s.subscriber:raise HTTPException(409,'live_subscriber_exists')
        s.subscriber=True
        async def generate():
            serial=0
            try:
                while True:
                    s.changed.clear()
                    for event in list(s.events):
                        if event['serial']>serial:serial=event['serial'];yield 'data: '+json.dumps(event,ensure_ascii=False)+'\n\n'
                    if s.closed or await request.is_disconnected():break
                    try:await asyncio.wait_for(s.changed.wait(),2)
                    except TimeoutError:yield ': heartbeat\n\n'
            finally:
                s.subscriber=False
                await manager.close(s.id,device_id,client_id,profile_epoch or None,'client_events_disconnected')
        return StreamingResponse(generate(),media_type='text/event-stream',headers={'Cache-Control':'no-store','X-Accel-Buffering':'no'})
    @app.get('/api/v1/live/sessions/{ident}/status',dependencies=[Depends(auth)])
    async def session_status(ident:str,device_id:str,client_id:str,profile_epoch:str=''):
        valid_id(ident)
        s=owned(ident,{'device_id':device_id,'client_id':client_id,'profile_epoch':profile_epoch})
        return {'closing':s.closing,'closed':s.closed,'reason':s.close_reason,'final_usage_confirmed':s.final_usage_confirmed,
            'mode':s.mode_flow.public() if s.mode_flow else None}
    @app.post('/api/v1/live/identity/close',dependencies=[Depends(auth)])
    async def close_identity(request:Request):
        body=await bounded_json(request,2000)
        for flow in manager.modes.items.values():
            if (flow.owner,flow.client,flow.epoch)==(body.get('device_id'),body.get('client_id'),body.get('profile_epoch')):manager.modes.end(flow,'profile_changed')
        for s in list(manager.sessions.values()):
            if not s.closed and (s.offer.device_id,s.offer.client_id,s.offer.profile_epoch)==(body.get('device_id'),body.get('client_id'),body.get('profile_epoch')):
                await manager.close(s.id,s.offer.device_id,s.offer.client_id,s.offer.profile_epoch,'profile_changed')
        return {'closed':True}
    @app.post('/api/v1/live/modes/{ident}/command',dependencies=[Depends(auth)])
    async def mode_command(ident:str,request:Request):
        from pydantic import BaseModel,ConfigDict
        from typing import Literal
        class Command(BaseModel):
            model_config=ConfigDict(extra='forbid')
            action:Literal['activity','live','legacy','end']
            input_active:bool=False
            playback_active:bool=False
        body=await bounded_json(request,2000)
        scope={k:body.pop(k,None) for k in ['device_id','client_id','profile_epoch']}
        try:
            parsed=Command.model_validate(body)
            flow=manager.modes.owned(valid_id(ident),scope['device_id'],scope['client_id'],scope['profile_epoch'])
            if parsed.action=='end':
                manager.modes.end(flow,'conversation_ended')
                s=manager.sessions.get(flow.provider_session)
                if s and not s.closed:await manager.close(s.id,flow.owner,flow.client,flow.epoch,'conversation_ended')
            elif parsed.action=='activity':
                if flow.active:manager.modes.activity(flow,parsed.input_active,parsed.playback_active)
            else:
                if flow.legacy_turn:raise PermissionError('conversation_mode_busy')
                manager.modes.select(flow,parsed.action)
                s=manager.sessions.get(flow.provider_session)
                if s and not s.closed:
                    if parsed.action=='legacy':await manager.close(s.id,flow.owner,flow.client,flow.epoch,'mode_switch')
                    else:raise PermissionError('conversation_mode_already_live')
            return flow.public()
        except ValidationError:raise HTTPException(422,'invalid_mode_command')
        except PermissionError as error:raise HTTPException(403,str(error))
    @app.post('/api/v1/live/sessions/{ident}/speaker',dependencies=[Depends(auth)])
    async def speaker(ident:str,request:Request,device_id:str,client_id:str,segment_id:str,profile_epoch:str=''):
        valid_id(ident)
        s=owned(ident,{'device_id':device_id,'client_id':client_id,'profile_epoch':profile_epoch})
        if request.headers.get('content-type')!='audio/pcm;rate=16000':raise HTTPException(422,'speaker_pcm16_required')
        raw=bytearray()
        async for part in request.stream():
            raw.extend(part)
            if len(raw)>192000:raise HTTPException(413,'speaker_audio_too_large')
        try:return await s.speaker.accept(segment_id,bytes(raw))
        except ValueError:raise HTTPException(409,'stale_speaker_segment')

def attach_gateway_live(app,settings,devices,subject,device_scope,profile_epoch):
    base='http://127.0.0.1:18781/api/v1/live';auth={'Authorization':'Bearer '+settings.api_token}
    async def identity(request):
        owner=await subject(request);profile=await asyncio.to_thread(devices.profile,device_scope(request,owner))
        return {'device_id':owner,'client_id':profile.client_id,'profile_epoch':profile_epoch(request,owner)}
    async def forward(method,path,*,params=None,body=None,timeout=20):
        async with httpx.AsyncClient(trust_env=False,timeout=timeout) as c:r=await c.request(method,base+path,headers=auth,params=params,json=body)
        try:data=r.json()
        except ValueError:data={'detail':'live_backend_invalid_response'}
        return JSONResponse(data,status_code=r.status_code if r.status_code>=400 else (502 if data=={'detail':'live_backend_invalid_response'} else r.status_code),headers={'Cache-Control':'no-store'})
    @app.get('/api/live/status')
    async def status(request:Request):
        device='browser-'+request.client.host.replace('.','-')
        binding=(await asyncio.to_thread(devices.profile,device_scope(request,device))).client_id
        return await forward('GET','/status',params={'binding':binding},timeout=5)
    @app.post('/api/live/sessions')
    async def create(request:Request):
        body=await bounded_json(request)
        allowed={'session_id','conversation_id','sdp','consent','requested_model','requested_voice','requested_expert_profile','personalization_mode','input_mode','remember','speaker_consent','client_kind','conversation_mode','mode_conversation_id'}
        if set(body)-allowed:raise HTTPException(422,'live_client_configuration_denied')
        body.update(await identity(request))
        device='browser-'+request.client.host.replace('.','-')
        body['owner_test_binding']=(await asyncio.to_thread(devices.profile,device_scope(request,device))).client_id
        body['expert_quota_consent']=True # Effective server owner policy still gates every launch.
        if body['device_id'].startswith('personal:'):
            import base64
            value=request.cookies['gobot_profile'].rsplit('.',1)[0]
            body['confirmed_profile_epoch']=json.loads(base64.urlsafe_b64decode(value+'='*(-len(value)%4)))['epoch']
        try:LiveOffer.model_validate(body)
        except ValidationError:raise HTTPException(422,'invalid_live_offer')
        return await forward('POST','/sessions',body=body,timeout=55)
    @app.post('/api/live/sessions/{ident}/command')
    async def command(ident:str,request:Request):
        valid_id(ident)
        body=await bounded_json(request,16000)
        try:LiveCommand.model_validate(body)
        except ValidationError:raise HTTPException(422,'invalid_live_command')
        body.update(await identity(request));return await forward('POST','/sessions/'+ident+'/command',body=body,timeout=25)
    @app.post('/api/live/modes/{ident}/command')
    async def mode_command(ident:str,request:Request):
        valid_id(ident);body=await bounded_json(request,2000)
        if set(body)-{'action','input_active','playback_active'}:raise HTTPException(422,'invalid_mode_command')
        body.update(await identity(request));return await forward('POST','/modes/'+ident+'/command',body=body,timeout=25)
    @app.get('/api/live/sessions/{ident}/events')
    async def events(ident:str,request:Request):
        valid_id(ident)
        scope=await identity(request)
        async def generate():
            async with httpx.AsyncClient(trust_env=False,timeout=None) as c:
                async with c.stream('GET',base+'/sessions/'+ident+'/events',headers=auth,params={k:v or '' for k,v in scope.items()}) as r:
                    if r.status_code!=200:return
                    async for part in r.aiter_bytes():yield part
        return StreamingResponse(generate(),media_type='text/event-stream',headers={'Cache-Control':'no-store','X-Accel-Buffering':'no'})
    @app.post('/api/live/sessions/{ident}/speaker')
    async def speaker(ident:str,request:Request,segment_id:str):
        valid_id(ident)
        scope=await identity(request);scope['segment_id']=segment_id
        raw=bytearray()
        async for part in request.stream():
            raw.extend(part)
            if len(raw)>192000:raise HTTPException(413,'speaker_audio_too_large')
        async with httpx.AsyncClient(trust_env=False,timeout=10) as c:
            r=await c.post(base+'/sessions/'+ident+'/speaker',headers={**auth,'Content-Type':request.headers.get('Content-Type','')},params={k:v or '' for k,v in scope.items()},content=raw)
        return JSONResponse(r.json(),status_code=r.status_code,headers={'Cache-Control':'no-store'})
    @app.get('/api/live/sessions/{ident}/status')
    async def session_status(ident:str,request:Request):
        valid_id(ident)
        return await forward('GET','/sessions/'+ident+'/status',params={k:v or '' for k,v in (await identity(request)).items()},timeout=3)
    previous=getattr(app.state,'close_realtime_identity',None)
    async def close_identity(request):
        if previous:await previous(request)
        result=await forward('POST','/identity/close',body=await identity(request),timeout=45)
        if result.status_code!=200:raise HTTPException(503,'live_identity_cleanup_unconfirmed')
    app.state.close_realtime_identity=close_identity
