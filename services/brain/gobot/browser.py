"""Private HTTPS browser transport. Brain and Agent Bridge remain loopback-only."""
import asyncio
import json
from pathlib import Path
import time
import base64,hashlib,hmac,re

import httpx
from fastapi import FastAPI, Request, HTTPException,WebSocket,WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from .models import VoiceRequest
from pydantic import ValidationError
from contextlib import asynccontextmanager
from .antigravity_login import AntigravityLogin
from .device_store import DeviceStore
from .activation import WakeWordActivationService
from .telemetry import Trace,Traces

from .secrets_store import openai_key_present, save_openai_key

ROOT = Path(__file__).resolve().parents[3]
HOST = "plan.tailffc57c.ts.net"
PORT = 18786
ORIGIN = "https://" + HOST + ":" + str(PORT)
PEERS = {"100.120.201.115", "100.90.228.125"}

def create_browser_app(settings=None):
    if settings is None:
        from .config import load
        settings=load()
    traces=Traces(Path(settings.db).resolve().parent)
    login=AntigravityLogin();devices=DeviceStore(Path(settings.db).resolve().parent/'browser-devices')
    @asynccontextmanager
    async def lifespan(app):
        yield
        await login.close()
    app = FastAPI(lifespan=lifespan,docs_url=None, redoc_url=None, openapi_url=None)
    slots=asyncio.Semaphore(2)
    auth={'Authorization':'Bearer '+settings.api_token}
    def device(request):return 'browser-'+request.client.host.replace('.','-')
    def device_scope(request,owner):return owner+'@'+request.client.host
    def profile_epoch(request,owner):
        if owner.startswith('personal:'):
            return hmac.new(settings.api_token.encode(),request.cookies.get('gobot_profile','').encode(),hashlib.sha256).hexdigest()[:24]
        return None
    async def allow_prefetch(request,owner,requested):
        if not requested:return False
        profile=await asyncio.to_thread(devices.profile,device_scope(request,owner))
        screen=profile.screen
        return screen.automatic_illustrations and screen.prefer_real_photos and screen.style!='minimal'
    async def subject(request):
        value=request.cookies.get('gobot_profile','')
        try:
            payload,signature=value.rsplit('.',1)
            expected=hmac.new(settings.api_token.encode(),('profile:'+payload).encode(),hashlib.sha256).hexdigest()
            if not hmac.compare_digest(signature,expected):raise ValueError()
            obj=json.loads(base64.urlsafe_b64decode(payload+'='*(-len(payload)%4)))
            if obj['peer']!=request.client.host or obj['expires']<time.time():raise ValueError()
            async with httpx.AsyncClient(trust_env=False,timeout=2) as client:
                response=await client.post('http://127.0.0.1:18781/api/v1/family/session',headers=auth,json={'id':obj['id'],'epoch':obj['epoch']})
                if not response.json().get('valid'):raise ValueError()
            return 'personal:'+obj['id']
        except Exception:return device(request)

    from .realtime_api import attach_gateway_realtime
    attach_gateway_realtime(app,settings,devices,subject,device_scope,profile_epoch)
    from .live_api import attach_gateway_live
    attach_gateway_live(app,settings,devices,subject,device_scope,profile_epoch)
    from .demo2 import attach_demo2
    attach_demo2(app)

    @app.get('/api/demo2/a/readiness')
    async def legacy_readiness(request:Request):
        owner=await subject(request)
        profile=await asyncio.to_thread(devices.profile,device_scope(request,owner))
        try:grant=json.loads((ROOT/'run/legacy-owner-admission.json').read_text(encoding='utf-8'))
        except (OSError,ValueError):grant={}
        allowed=bool(grant.get('enabled') and grant.get('authorization') and grant.get('allowed_client_id')==profile.client_id)
        from .live_agents import agent_status
        agents=await asyncio.to_thread(agent_status,allowed)
        return JSONResponse({'manual_authorized':allowed,'automatic_calls':False,'engine':'legacy',
            'grant_revision':hashlib.sha256(str(grant.get('authorization','')).encode()).hexdigest()[:16] if allowed else None,
            'stt':'gpt-transcribe','cli_provider':'antigravity','cli_model':settings.router.fast_cli_model,
            'voice':'marin','voice_formatter':'legacy Russian Speech Formatter',
            'cli_ready':agents['antigravity']['available'],'cli_reason':agents['antigravity']['reason'],
            'openai_key_configured':openai_key_present()},headers={'Cache-Control':'no-store'})

    @app.post('/api/chat/stream')
    async def chat(request:Request):
        timing=Trace('pending','gateway-chat');timing.mark('request_received')
        downgraded=False
        raw=bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw)>20000:raise HTTPException(413,'request_too_large')
        try:
            body=json.loads(raw)
            timing.id=str(body.get('trace_id') or body.get('utterance_id') or body.get('turn_id') or 'chat')[:100];timing.mark('profile_start')
            body['device_id']=await subject(request)
            timing.mark('profile_end')
            if body.get('speaker_job_id') and not re.fullmatch(r'[a-f0-9-]{36}',str(body['speaker_job_id'])):raise ValueError('invalid_speaker_job')
            if body.get('speaker_job_id') and body['device_id'].startswith('personal:'):
                async with httpx.AsyncClient(trust_env=False,timeout=2) as client:
                    identity=(await client.get('http://127.0.0.1:18781/api/v1/speaker/'+str(body['speaker_job_id']),headers=auth,params={'device_id':device(request)})).json()
                matched=identity.get('state')=='recognized' and 'personal:'+str(identity.get('profile_id'))==body['device_id']
                short=identity.get('state')=='insufficient_audio' and identity.get('reason')=='short_segment'
                if not matched and not short:
                    from uuid import uuid5,NAMESPACE_URL
                    body['device_id']=device(request)
                    body['conversation_id']=str(uuid5(NAMESPACE_URL,str(body.get('conversation_id',''))+':guest:'+device(request)))
                    downgraded=True
            profile=await asyncio.to_thread(devices.profile,device_scope(request,body['device_id']))
            body['profile_epoch']=profile_epoch(request,body['device_id'])
            body['screen_preferences']=profile.screen.model_dump()
            body['client_id']=profile.client_id # Trusted scope for conversational settings in both clients.
            body.setdefault('mode','auto')
            req=VoiceRequest.model_validate(body)
        except (ValueError,TypeError,AttributeError):raise HTTPException(422,'invalid_chat_request')
        timing.mark('gateway_queue_start')
        try:await asyncio.wait_for(slots.acquire(),.1)
        except TimeoutError:raise HTTPException(429,'busy')
        timing.mark('gateway_queue_end')
        async def generate():
            try:
                if downgraded:
                    yield 'event: tool_status\ndata: '+json.dumps({'type':'tool_status','data':{'status':'guest_context','conversation_id':req.conversation_id}})+'\n\n'
                async with httpx.AsyncClient(trust_env=False,timeout=httpx.Timeout(150,connect=2)) as client:
                    async with client.stream('POST','http://127.0.0.1:18781/api/v1/chat/voice/stream',headers=auth,json=req.model_dump()) as response:
                        if response.status_code!=200:
                            yield 'event: error\ndata: {"type":"error","data":{"code":"brain_request_failed"}}\n\n'
                            return
                        async for chunk in response.aiter_bytes():
                            timing.mark('brain_first_bytes');yield chunk
            except httpx.HTTPError:
                yield 'event: error\ndata: {"type":"error","data":{"code":"brain_unavailable"}}\n\n'
            finally:
                timing.mark('gateway_closed');await asyncio.to_thread(traces.save,req.device_id,timing);slots.release()
        result=StreamingResponse(generate(),media_type='text/event-stream',headers={'X-Accel-Buffering':'no'})
        if downgraded:result.delete_cookie('gobot_profile')
        return result

    @app.post('/api/audio/transcribe')
    async def transcribe(request:Request):
        ident=request.query_params.get('trace_id') or 'upload'
        if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,100}',ident):raise HTTPException(422)
        trace=Trace(ident,'gateway-stt');trace.mark('upload_first')
        raw=bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw)>8*1024*1024:raise HTTPException(413,'audio_too_large')
        trace.mark('upload_last',input_bytes=len(raw));owner=await subject(request)
        prefetch=await allow_prefetch(request,owner,request.query_params.get('visual_prefetch')=='true')
        async with slots:
            trace.mark('stt_gateway_queue_end')
            try:
                async with httpx.AsyncClient(trust_env=False,timeout=120) as client:
                    response=await client.post('http://127.0.0.1:18781/api/v1/audio/transcribe',content=bytes(raw),params={
                        'provider':request.query_params.get('provider','openai'),'paid_consent':request.query_params.get('paid_consent','false'),
                        'device_id':device(request),'trace_id':request.query_params.get('trace_id'),'trace_owner':owner,'visual_prefetch':prefetch,
                        'visual_epoch':profile_epoch(request,owner) or ''},headers={**auth,'Content-Type':request.headers.get('content-type','')})
                trace.mark('stt_returned');result=response.json();result['gateway_telemetry']=trace.snapshot();await asyncio.to_thread(traces.save,owner,trace)
                return JSONResponse(result,status_code=response.status_code)
            except httpx.HTTPError:raise HTTPException(503,'stt_unavailable')

    @app.get('/api/history/{conversation}')
    async def history(conversation:str,request:Request):
        if not __import__('re').fullmatch(r'[A-Za-z0-9_.:-]{1,100}',conversation):raise HTTPException(422)
        async with httpx.AsyncClient(trust_env=False,timeout=3) as client:
            response=await client.get('http://127.0.0.1:18781/api/v1/history/'+conversation,params={'device_id':await subject(request)},headers=auth)
            return JSONResponse(response.json(),status_code=response.status_code)

    @app.api_route('/api/memory',methods=['GET','POST'])
    async def memory_proxy(request:Request):
        owner=await subject(request)
        async with httpx.AsyncClient(trust_env=False,timeout=5) as client:
            if request.method=='GET':
                conversation=request.query_params.get('conversation_id','')
                if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,100}',conversation):raise HTTPException(422)
                result=await client.get('http://127.0.0.1:18781/api/v1/memory',headers=auth,params={'device_id':owner,'conversation_id':conversation})
            else:
                raw=await request.body()
                if len(raw)>12000:raise HTTPException(413)
                try:body=json.loads(raw);body['device_id']=owner
                except (ValueError,TypeError):raise HTTPException(422)
                result=await client.post('http://127.0.0.1:18781/api/v1/memory',headers=auth,json=body)
            return JSONResponse(result.json(),status_code=result.status_code)

    @app.get('/api/memory/source/{message_id}')
    async def source_proxy(message_id:int,request:Request):
        async with httpx.AsyncClient(trust_env=False,timeout=3) as client:
            result=await client.get('http://127.0.0.1:18781/api/v1/memory/source/'+str(message_id),params={'device_id':await subject(request)},headers=auth)
            return JSONResponse(result.json(),status_code=result.status_code)

    @app.post('/api/audio/playback')
    async def playback_proxy(request:Request):
        raw=await request.body()
        if len(raw)>4096:raise HTTPException(413)
        try:body=json.loads(raw);body['device_id']=await subject(request)
        except (ValueError,TypeError):raise HTTPException(422)
        async with httpx.AsyncClient(trust_env=False,timeout=2) as client:
            result=await client.post('http://127.0.0.1:18781/api/v1/audio/playback',headers=auth,json=body)
            return JSONResponse(result.json(),status_code=result.status_code)

    @app.get('/api/visual/assets/{asset}/{variant}.jpg')
    async def visual_asset(asset:str,variant:str):
        from fastapi import Response
        if not re.fullmatch(r'[a-f0-9]{64}',asset) or variant not in {'browser','preview','device'}:raise HTTPException(404)
        async with httpx.AsyncClient(trust_env=False,timeout=5) as client:
            response=await client.get('http://127.0.0.1:18781/api/v1/visual/assets/'+asset+'/'+variant+'.jpg',headers=auth)
        if response.status_code!=200:raise HTTPException(404,'image_expired_or_missing')
        limit=65536 if variant=='device' else 2*1024*1024
        if response.headers.get('content-type')!='image/jpeg' or len(response.content)>limit:raise HTTPException(502,'invalid_image_variant')
        return Response(response.content,media_type='image/jpeg',headers={'Content-Length':str(len(response.content)),'X-Content-Type-Options':'nosniff'})

    @app.post('/api/visual/timer/cancel')
    async def cancel_timer_proxy(request:Request):
        body=await request.json()
        if not isinstance(body,dict) or set(body)-{'timer_id'}:raise HTTPException(422)
        body['device_id']=await subject(request)
        profile=await asyncio.to_thread(devices.profile,device_scope(request,body['device_id']));body['client_id']=profile.client_id
        async with httpx.AsyncClient(trust_env=False,timeout=3) as client:
            response=await client.post('http://127.0.0.1:18781/api/v1/visual/timer/cancel',headers=auth,json=body)
        return JSONResponse(response.json(),status_code=response.status_code)

    @app.get('/api/settings/visual')
    async def visual_settings():
        from .visual_images import source_config
        config=source_config()
        return {'configured':bool(config),'contact':config.get('contact',''),'provider':config.get('provider','disabled'),'private_history_sent':False}
    @app.get('/api/visual/generation/usage')
    async def generation_usage(request:Request):
        owner=await subject(request)
        profile=await asyncio.to_thread(devices.profile,device_scope(request,owner))
        async with httpx.AsyncClient(trust_env=False,timeout=3) as client:
            response=await client.get('http://127.0.0.1:18781/api/v1/visual/generation/usage',params={'device_id':'visual-device:'+profile.client_id},headers=auth)
            return JSONResponse(response.json(),status_code=response.status_code)

    @app.post('/api/settings/visual')
    async def save_visual_settings(request:Request):
        from .visual_images import CONTACT,valid_contact
        raw=await request.body()
        if len(raw)>2048:raise HTTPException(413)
        try:body=json.loads(raw);contact=body.get('contact','').strip();provider=body.get('provider','wikimedia')
        except (ValueError,TypeError,KeyError,AttributeError):raise HTTPException(422,'invalid_public_contact')
        if set(body)-{'contact','public_contact_consent','provider'} or provider not in {'openverse','wikimedia','disabled'}:raise HTTPException(422,'invalid_image_provider')
        if provider=='wikimedia' and (body.get('public_contact_consent') is not True or not valid_contact(contact)):raise HTTPException(422,'valid_public_contact_and_consent_required')
        config={'provider':provider}
        if provider=='wikimedia':config['contact']=contact
        CONTACT.parent.mkdir(exist_ok=True);temporary=CONTACT.with_suffix('.tmp');temporary.write_text(json.dumps(config),encoding='utf-8');temporary.replace(CONTACT)
        return {'configured':provider!='disabled','provider':provider,'connection_verified':False}

    @app.get('/api/speaker/{job}')
    async def speaker_status(job:str,request:Request):
        if not re.fullmatch(r'[a-f0-9-]{36}',job):raise HTTPException(422)
        async with httpx.AsyncClient(trust_env=False,timeout=3) as client:
            result=await client.get('http://127.0.0.1:18781/api/v1/speaker/'+job,params={'device_id':device(request)},headers=auth)
            return JSONResponse(result.json(),status_code=result.status_code)

    @app.websocket('/api/audio/live')
    async def live_audio(ws:WebSocket):
        if not ws.client or ws.client.host not in PEERS or ws.headers.get('host')!=HOST+':'+str(PORT) or ws.headers.get('origin')!=ORIGIN:
            await ws.close(code=4403);return
        await ws.accept()
        from websockets.asyncio.client import connect
        try:
            async with slots:
                async with asyncio.timeout(100):
                    raw=await asyncio.wait_for(ws.receive_text(),5)
                    if len(raw)>4096:raise ValueError()
                    config=json.loads(raw);config['device_id']=device(ws)
                    config['visual_owner']=await subject(ws)
                    config['visual_epoch']=profile_epoch(ws,config['visual_owner'])
                    config['visual_prefetch']=await allow_prefetch(ws,config['visual_owner'],config.get('visual_prefetch') is True)
                    async with connect('ws://127.0.0.1:18781/api/v1/audio/live',additional_headers=auth,proxy=None,max_size=1048576,max_queue=4) as remote:
                        await remote.send(json.dumps(config))
                        async def upload():
                            total=0
                            while True:
                                item=await ws.receive()
                                if item['type']=='websocket.disconnect':return
                                if item.get('text')=='end':
                                    await remote.send('end')
                                    await ws.receive()
                                    return
                                raw=item.get('bytes',b'');total+=len(raw)
                                if not raw or len(raw)>48000 or total>2880000:raise ValueError()
                                await remote.send(raw)
                        async def download():
                            async for raw in remote:
                                await ws.send_text(raw)
                                if json.loads(raw).get('type') in {'stt_final','error'}:return
                        sender=asyncio.create_task(upload());receiver=asyncio.create_task(download())
                        try:
                            done,_=await asyncio.wait({sender,receiver},return_when=asyncio.FIRST_COMPLETED)
                            if receiver not in done:
                                if sender.exception():raise sender.exception()
                                # Normal end commits; a disconnect must terminate upstream promptly.
                                if ws.client_state.name=='DISCONNECTED':return
                                await receiver
                        finally:
                            sender.cancel();receiver.cancel();await asyncio.gather(sender,receiver,return_exceptions=True)
        except (WebSocketDisconnect,asyncio.CancelledError):pass
        except Exception:
            with __import__('contextlib').suppress(Exception):await ws.send_json({'type':'error','data':{'code':'live_transport_unavailable'}})
        finally:
            with __import__('contextlib').suppress(Exception):await ws.close()

    attempts={}
    @app.api_route('/api/family/{action:path}',methods=['GET','POST','DELETE'])
    async def family_proxy(action:str,request:Request):
        fixed={'','login','logout','calibrate','unknown','fact','voices'}
        if action not in fixed and not re.fullmatch(r'[a-f0-9-]{36}(?:/(?:enable|voice|sample|preferences))?',action):raise HTTPException(404)
        if action=='logout':
            await app.state.close_realtime_identity(request)
            response=JSONResponse({'logged_out':True});response.delete_cookie('gobot_profile');return response
        if action=='login' and request.method=='POST':
            now=time.monotonic();recent=[t for t in attempts.get(request.client.host,[]) if now-t<300]
            if len(recent)>=5:raise HTTPException(429,'too_many_pin_attempts')
            attempts[request.client.host]=recent+[now]
        from .family_api import bounded
        raw=await bounded(request,8*1024*1024 if action.endswith('/sample') else 8192)
        if action.endswith('/preferences'):
            if request.method!='POST':raise HTTPException(405)
            owner=await subject(request)
            if not owner.startswith('personal:') or owner!='personal:'+action.split('/')[0]:raise HTTPException(403,'confirmed_own_profile_required')
            try:
                data=json.loads(raw)
                if not isinstance(data,dict) or set(data)-{'operation','preferences','expected_revision'}:raise ValueError()
                payload=request.cookies['gobot_profile'].rsplit('.',1)[0]
                confirmed=json.loads(base64.urlsafe_b64decode(payload+'='*(-len(payload)%4)))
                data.update(actor_id=confirmed['id'],actor_epoch=confirmed['epoch']);raw=json.dumps(data).encode()
            except (ValueError,KeyError,TypeError):raise HTTPException(422,'invalid_preference_request')
        if action=='fact':
            try:
                data=json.loads(raw)
                if data.get('scope')=='personal':
                    data['scope_id']=await subject(request)
                    if not data['scope_id'].startswith('personal:'):raise HTTPException(403,'profile_pin_required')
                else:data['scope_id']='family:home'
                raw=json.dumps(data).encode()
            except (ValueError,AttributeError):raise HTTPException(422,'invalid_fact')
        async with httpx.AsyncClient(trust_env=False,timeout=75) as client:
            result=await client.request(request.method,'http://127.0.0.1:18781/api/v1/family'+('/'+action if action else ''),
                params={'kind':request.query_params.get('kind','enroll'),'sample_consent':request.query_params.get('sample_consent','false')} if action.endswith('/sample') else None,
                content=raw,headers={**auth,'Content-Type':request.headers.get('content-type','application/json')})
        if action=='login' and result.status_code==200:
            await app.state.close_realtime_identity(request)
            data=result.json();data.update({'peer':request.client.host,'expires':time.time()+86400})
            payload=base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip('=')
            signature=hmac.new(settings.api_token.encode(),('profile:'+payload).encode(),hashlib.sha256).hexdigest()
            response=JSONResponse({'personal_context':True,'name':data['name']})
            response.set_cookie('gobot_profile',payload+'.'+signature,secure=True,httponly=True,samesite='strict',max_age=86400)
            attempts[request.client.host]=[];return response
        return JSONResponse(result.json(),status_code=result.status_code)

    @app.get('/feedback-wait.wav')
    async def feedback_wait():raise HTTPException(410,'legacy_denis_filler_retired')

    @app.get('/api/speech/openings/{voice}/{ident}.wav')
    async def speech_opening(voice:str,ident:str):
        from .speech_openings import OpeningCache
        clip=await asyncio.to_thread(OpeningCache().clip,voice,ident)
        if clip is None:raise HTTPException(404,'opening_clip_unavailable')
        return FileResponse(clip['path'],media_type='audio/wav',headers={'Cache-Control':'private, max-age=86400'})

    @app.get('/api/speech/openings/status/{voice}')
    async def speech_opening_status(voice:str):
        from .speech_openings import OpeningCache,OPENAI_VOICES
        if voice not in OPENAI_VOICES:raise HTTPException(404)
        return await asyncio.to_thread(OpeningCache().status,voice)

    @app.get('/audio/voice-check.wav')
    async def voice_check():
        path=ROOT/'data/openai-voice-owner-approved.wav'
        if not path.exists():raise HTTPException(404,'owner_approved_voice_probe_not_run')
        return FileResponse(path,media_type='audio/wav')

    @app.middleware("http")
    async def perimeter(request: Request, call_next):
        if not request.client or request.client.host not in PEERS:
            return JSONResponse({"error": "trusted_tailnet_device_required"}, status_code=403)
        if request.headers.get("host", "").lower() != HOST + ":" + str(PORT):
            return JSONResponse({"error": "host_denied"}, status_code=403)
        if request.headers.get("origin") not in {None, ORIGIN} or request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse({"error": "origin_denied"}, status_code=403)
        if request.method != "GET" and request.headers.get("origin") != ORIGIN:
            return JSONResponse({"error": "same_origin_required"}, status_code=403)
        response = await call_next(request)
        response.headers.update({"Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
                                 "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
                                 "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob:; connect-src 'self' wss://plan.tailffc57c.ts.net:18786; media-src 'self' blob:; worker-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
                                 "Permissions-Policy": "microphone=(self), camera=(), geolocation=()"})
        return response

    @app.get("/healthz")
    async def health():
        return {"status": "ok", "transport": "private-tailnet-https"}

    @app.get("/settings/openai")
    async def key_form():
        return FileResponse(ROOT / "services/phone/dist/openai-key.html", media_type="text/html")

    @app.get('/settings/google')
    async def google_form():return FileResponse(ROOT/'services/phone/dist/google-login.html',media_type='text/html')
    @app.get('/settings/gemini')
    async def retired_gemini():raise HTTPException(410,'Gemini CLI retired; use /settings/google')
    @app.get('/settings/family')
    async def family_form():return FileResponse(ROOT/'services/phone/dist/family.html',media_type='text/html')
    @app.get('/api/settings/google')
    async def gemini_status():return login.status()
    @app.post('/api/settings/google/start')
    async def gemini_start():return await login.start()
    @app.post('/api/settings/google/cancel')
    async def gemini_cancel():
        await login.close();return login.status()
    @app.post('/api/settings/google/code')
    async def gemini_code(request:Request):
        raw=bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw)>4096:raise HTTPException(413,'request_too_large')
        try:
            body=json.loads(raw)
            return await login.submit(body.get('code'))
        except (ValueError,TypeError,AttributeError):raise HTTPException(422,'invalid_or_expired_code')

    @app.get("/api/settings/openai")
    async def key_status():
        return {"configured": openai_key_present(), "storage": "Windows DPAPI, current user",
                "key_returned": False, "api_request_made": False}

    @app.post("/api/settings/openai")
    async def key_save(request: Request):
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > 4096:
                raise HTTPException(413, "request_too_large")
        try:
            body = json.loads(data)
            value = body.get("key") if isinstance(body, dict) else None
            await asyncio.to_thread(save_openai_key, value)
        except (ValueError, TypeError):
            raise HTTPException(422, "invalid_key_format")
        except RuntimeError:
            raise HTTPException(503, "secure_storage_unavailable")
        return {"saved": True, "api_request_made": False}

    @app.get("/api/status")
    async def status():
        services = []
        async with httpx.AsyncClient(trust_env=False, timeout=2) as client:
            for name, port in [("Brain", 18781), ("Bridge", 18782), ("Голосовой стенд", 18783), ("Изображения", 18784)]:
                try:
                    response = await client.get("http://127.0.0.1:" + str(port) + "/healthz")
                    ok = response.status_code == 200
                except httpx.HTTPError:
                    ok = False
                services.append({"name": name, "ok": ok})
            try:
                backend=(await client.get('http://127.0.0.1:18781/api/v1/status',headers=auth)).json()
            except httpx.HTTPError:backend={}
        return {"services": services, "remaining_seconds": None, "mode": "development",
                "backend":backend,"openai_key_configured": openai_key_present()}

    @app.get("/")
    async def index():
        return unified_page('browser.html')

    def unified_page(name):
        html=(ROOT/'services/phone/dist'/name).read_text(encoding='utf-8')
        html=html.replace('<body','<body data-conversation-engine="live" data-unified="true"',1)
        html=html.replace('</head>','<script src="/unified.js" defer></script></head>')
        html=html.replace('Браузерный прототип','GoBot · C ↔ A')
        return HTMLResponse(html,headers={'Cache-Control':'no-store','X-GoBot-Conversation':'live-legacy-unified'})

    @app.api_route('/api/telemetry/{ident}',methods=['GET','POST'])
    async def telemetry(request:Request,ident:str):
        if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,100}',ident):raise HTTPException(422)
        owner=await subject(request)
        async with httpx.AsyncClient(trust_env=False,timeout=3) as client:
            if request.method=='POST':
                raw=await request.body()
                if len(raw)>16384:raise HTTPException(413)
                try:body=json.loads(raw);body['trace_id']=ident;body['device_id']=owner
                except (ValueError,TypeError):raise HTTPException(422)
                result=await client.post('http://127.0.0.1:18781/api/v1/telemetry',headers=auth,json=body)
            else:result=await client.get('http://127.0.0.1:18781/api/v1/telemetry/'+ident,headers=auth,params={'device_id':owner})
        return JSONResponse(result.json(),status_code=result.status_code)

    @app.get('/device')
    async def device_page():return unified_page('device.html')

    @app.get('/api/device/profile')
    async def device_profile(request:Request):
        profile=await asyncio.to_thread(devices.profile,device_scope(request,await subject(request)))
        return {'profile':profile.model_dump(),'capabilities':profile.capabilities(),'activation':WakeWordActivationService().status()}

    @app.post('/api/device/profile')
    async def device_profile_save(request:Request):
        body=bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body)>16000:raise HTTPException(413)
        try:profile=await asyncio.to_thread(devices.update,device_scope(request,await subject(request)),json.loads(body))
        except (ValueError,TypeError):raise HTTPException(422,'invalid_device_profile')
        return {'profile':profile.model_dump(),'capabilities':profile.capabilities()}

    @app.post('/api/device/screensaver')
    async def screensaver_upload(request:Request):
        body=bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body)>2*1024*1024:raise HTTPException(413)
        try:await asyncio.to_thread(devices.upload,device_scope(request,await subject(request)),bytes(body),request.headers.get('content-type','').split(';')[0])
        except Exception:raise HTTPException(422,'invalid_screensaver')
        return {'saved':True,'raw_upload_saved':False}

    @app.get('/api/device/screensaver')
    async def screensaver_get(request:Request):
        from fastapi.responses import Response
        try:data=await asyncio.to_thread(devices.image,device_scope(request,await subject(request)))
        except (OSError,KeyError,ValueError):raise HTTPException(404)
        return Response(data,media_type='image/jpeg')

    @app.delete('/api/device/screensaver')
    async def screensaver_delete(request:Request):
        await asyncio.to_thread(devices.remove_image,device_scope(request,await subject(request)));return {'deleted':True}

    @app.get('/api/device/timers')
    async def device_timers(request:Request):
        owner=await subject(request);profile=await asyncio.to_thread(devices.profile,device_scope(request,owner))
        async with httpx.AsyncClient(trust_env=False,timeout=3) as client:
            result=await client.get('http://127.0.0.1:18781/api/v1/timers',headers=auth,params={'device_id':owner,'client_id':profile.client_id})
            return JSONResponse(result.json(),status_code=result.status_code)

    @app.get("/{asset}")
    async def static(asset: str):
        assets = {name:'text/javascript' for name in ['app.js','browser.js','realtime.js','live.js','realtime-speaker.js','expert-ui.js','owner-test-ui.js','visual.js','key.js','google-login.js','capture.js','pcm-worklet.js','family.js','family-preferences.js','turn-trace.js','device.js','device-renderer.js','device-settings.js']}
        assets['style.css']='text/css'
        assets['unified.js']='text/javascript'
        assets.update({'design-data.js':'text/javascript','design-primitives.js':'text/javascript','design-reference.js':'text/javascript','visual-atlas.js':'text/javascript','visual-atlas.html':'text/html','visual-atlas.css':'text/css','design.css':'text/css','noto-sans.ttf':'font/ttf'})
        assets['device.css']='text/css';assets['manifest.webmanifest']='application/manifest+json'
        assets['device-icon-192.png']='image/png';assets['device-icon-512.png']='image/png'
        if asset not in assets:
            raise HTTPException(404)
        return FileResponse(ROOT / "services/phone/dist" / asset, media_type=assets[asset])

    return app
