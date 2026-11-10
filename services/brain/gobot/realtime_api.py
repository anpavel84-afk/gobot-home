"""Authenticated GoBot routes; browser never sees provider IDs or credentials."""
import asyncio,json,re,time
import httpx
from fastapi import Request,HTTPException,Depends
from fastapi.responses import StreamingResponse
from pydantic import ValidationError
from .realtime_contract import RealtimeOffer,RealtimeCommand
from .models import ID

async def bounded_json(request,limit=70000):
    raw=bytearray()
    async for part in request.stream():
        raw.extend(part)
        if len(raw)>limit:raise HTTPException(413,'request_too_large')
    try:
        value=json.loads(raw)
        if not isinstance(value,dict):raise ValueError()
        return value
    except (ValueError,TypeError):raise HTTPException(422,'invalid_realtime_request')

def attach_brain_realtime(app,manager,auth):
    @app.get('/api/v1/realtime/status',dependencies=[Depends(auth)])
    async def status():return manager.status()

    @app.post('/api/v1/realtime/sessions',dependencies=[Depends(auth)])
    async def create(request:Request):
        try:
            offer=RealtimeOffer.model_validate(await bounded_json(request))
            return await manager.start(offer)
        except PermissionError as e:raise HTTPException(403,str(e))
        except (ValueError,ValidationError):raise HTTPException(409,'realtime_invalid_or_conflicting_session')
        except Exception:raise HTTPException(502,'realtime_setup_failed')

    @app.post('/api/v1/realtime/identity/close',dependencies=[Depends(auth)])
    async def close_identity(request:Request):
        data=await bounded_json(request,1024)
        if set(data)!={'device_id','client_id','profile_epoch'}:raise HTTPException(422,'invalid_identity_scope')
        for s in list(manager.sessions.values()):
            if not s.closed and (s.offer.device_id,s.offer.client_id,s.offer.profile_epoch)==(data['device_id'],data['client_id'],data['profile_epoch']):
                await manager.close(s.id,s.offer.device_id,s.offer.client_id,s.offer.profile_epoch,'profile_or_device_changed')
        return {'closed':True}

    def owned(ident,owner,client,epoch):
        if not re.fullmatch(ID,ident):raise HTTPException(422,'invalid_session_id')
        try:return manager.owned(ident,owner,client,epoch or None)
        except KeyError:raise HTTPException(404,'realtime_session_not_found')

    @app.post('/api/v1/realtime/sessions/{ident}/command',dependencies=[Depends(auth)])
    async def command(ident:str,request:Request):
        body=await bounded_json(request,12000)
        owner=body.pop('device_id',None);client=body.pop('client_id',None);epoch=body.pop('profile_epoch',None)
        try:
            cmd=RealtimeCommand.model_validate(body)
            if cmd.action=='close':return await manager.close(ident,owner,client,epoch)
            s=owned(ident,owner,client,epoch)
            return await s.command(cmd)
        except KeyError:raise HTTPException(404,'realtime_session_not_found')
        except PermissionError:raise HTTPException(403,'realtime_budget_required')
        except (ValueError,ValidationError):raise HTTPException(409,'invalid_realtime_command')
        except Exception:
            await manager.close(ident,owner,client,epoch,'command_failed')
            raise HTTPException(502,'realtime_command_failed')

    @app.get('/api/v1/realtime/sessions/{ident}/events',dependencies=[Depends(auth)])
    async def events(ident:str,request:Request,device_id:str,client_id:str,profile_epoch:str=''):
        s=owned(ident,device_id,client_id,profile_epoch)
        if s.subscriber:raise HTTPException(409,'realtime_event_subscriber_exists')
        s.subscriber=True
        async def generate():
            serial=0
            try:
                while True:
                    s.changed.clear()
                    for item in list(s.events):
                        if item['serial']>serial:
                            serial=item['serial'];yield 'data: '+json.dumps(item,ensure_ascii=False)+'\n\n'
                    if s.closed:return
                    if await request.is_disconnected():return
                    try:await asyncio.wait_for(s.changed.wait(),2)
                    except TimeoutError:yield ': heartbeat\n\n'
            finally:
                s.subscriber=False
                await manager.close(ident,device_id,client_id,profile_epoch or None,'client_events_disconnected')
        return StreamingResponse(generate(),media_type='text/event-stream',headers={'X-Accel-Buffering':'no','Cache-Control':'no-store'})

    @app.post('/api/v1/realtime/sessions/{ident}/speaker',dependencies=[Depends(auth)])
    async def speaker(ident:str,request:Request,device_id:str,client_id:str,segment_id:str,profile_epoch:str=''):
        s=owned(ident,device_id,client_id,profile_epoch)
        raw=bytearray()
        async for part in request.stream():
            raw.extend(part)
            if len(raw)>192000:raise HTTPException(413,'speaker_audio_too_large')
        if request.headers.get('content-type')!='audio/pcm;rate=16000':raise HTTPException(422,'speaker_pcm16_16khz_required')
        try:return await s.speaker.accept(segment_id,bytes(raw))
        except ValueError:raise HTTPException(409,'stale_or_invalid_speaker_segment')

def attach_gateway_realtime(app,settings,devices,subject,device_scope,profile_epoch):
    auth={'Authorization':'Bearer '+settings.api_token}
    base='http://127.0.0.1:18781/api/v1/realtime'
    async def identity(request):
        owner=await subject(request)
        profile=await asyncio.to_thread(devices.profile,device_scope(request,owner))
        return {'device_id':owner,'client_id':profile.client_id,'profile_epoch':profile_epoch(request,owner)}
    async def close_identity(request):
        scope=await identity(request)
        async with httpx.AsyncClient(trust_env=False,timeout=20) as c:
            response=await c.post(base+'/identity/close',headers=auth,json=scope)
        if response.status_code!=200:raise HTTPException(503,'realtime_identity_cleanup_required')
    app.state.close_realtime_identity=close_identity

    @app.get('/api/realtime/status')
    async def status():
        try:
            async with httpx.AsyncClient(trust_env=False,timeout=3) as c:r=await c.get(base+'/status',headers=auth)
            return r.json()
        except Exception:return {'default_engine':'legacy','available':False,'code':'brain_unavailable'}

    @app.post('/api/realtime/sessions')
    async def create(request:Request):
        body=await bounded_json(request)
        allowed={'session_id','conversation_id','sdp','consent','remember','speak','client_kind','expert_quota_consent','personalization_mode','speaker_consent','requested_voice'}
        if set(body)-allowed:raise HTTPException(422,'client_configuration_denied')
        body.update(await identity(request))
        if body['device_id'].startswith('personal:'):
            import base64
            payload=request.cookies['gobot_profile'].rsplit('.',1)[0]
            confirmed=json.loads(base64.urlsafe_b64decode(payload+'='*(-len(payload)%4)))
            body['confirmed_profile_epoch']=confirmed['epoch']
        try:RealtimeOffer.model_validate(body)
        except ValidationError:raise HTTPException(422,'invalid_realtime_offer')
        async with httpx.AsyncClient(trust_env=False,timeout=35) as c:
            r=await c.post(base+'/sessions',headers=auth,json=body)
        if r.status_code!=200:raise HTTPException(r.status_code,'realtime_setup_not_available')
        return r.json()

    @app.post('/api/realtime/sessions/{ident}/command')
    async def command(ident:str,request:Request):
        if not re.fullmatch(ID,ident):raise HTTPException(422,'invalid_session_id')
        body=await bounded_json(request,12000)
        try:RealtimeCommand.model_validate(body)
        except ValidationError:raise HTTPException(422,'invalid_realtime_command')
        body.update(await identity(request))
        async with httpx.AsyncClient(trust_env=False,timeout=20) as c:
            r=await c.post(base+'/sessions/'+ident+'/command',headers=auth,json=body)
        if r.status_code!=200:raise HTTPException(r.status_code,'realtime_command_failed')
        return r.json()

    @app.get('/api/realtime/sessions/{ident}/events')
    async def events(ident:str,request:Request):
        if not re.fullmatch(ID,ident):raise HTTPException(422,'invalid_session_id')
        scope=await identity(request)
        async def generate():
            try:
                async with httpx.AsyncClient(trust_env=False,timeout=httpx.Timeout(None,connect=3)) as c:
                    async with c.stream('GET',base+'/sessions/'+ident+'/events',headers=auth,
                                        params={k:v or '' for k,v in scope.items()}) as r:
                        if r.status_code!=200:
                            yield 'data: {"type":"error","data":{"code":"realtime_session_unavailable"}}\n\n';return
                        checked=time.monotonic()
                        async for chunk in r.aiter_bytes():
                            if time.monotonic()-checked>2:
                                if await identity(request)!=scope:return
                                checked=time.monotonic()
                            if await request.is_disconnected():return
                            yield chunk
            except httpx.HTTPError:yield 'data: {"type":"error","data":{"code":"realtime_connection_lost"}}\n\n'
        return StreamingResponse(generate(),media_type='text/event-stream',headers={'X-Accel-Buffering':'no','Cache-Control':'no-store'})

    @app.post('/api/realtime/sessions/{ident}/speaker')
    async def speaker(ident:str,request:Request,segment_id:str):
        if not re.fullmatch(ID,ident) or not re.fullmatch(ID,segment_id):raise HTTPException(422,'invalid_identity_segment')
        if request.headers.get('content-type')!='audio/pcm;rate=16000':raise HTTPException(422,'speaker_pcm16_16khz_required')
        raw=bytearray()
        async for part in request.stream():
            raw.extend(part)
            if len(raw)>192000:raise HTTPException(413,'speaker_audio_too_large')
        scope=await identity(request)
        async with httpx.AsyncClient(trust_env=False,timeout=4) as c:
            r=await c.post(base+'/sessions/'+ident+'/speaker',headers={**auth,'Content-Type':'audio/pcm;rate=16000'},content=raw,
                           params={**{k:v or '' for k,v in scope.items()},'segment_id':segment_id})
        if r.status_code!=200:raise HTTPException(r.status_code,'speaker_segment_not_accepted')
        return r.json()
