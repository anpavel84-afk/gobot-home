"""Owner-only additive web preview on the existing Brain and HTTPS gateway."""
import asyncio,io,json,time,wave
from pathlib import Path
from uuid import uuid4
import httpx
from fastapi import Request,Depends,HTTPException
from fastapi.responses import JSONResponse,Response,FileResponse
from pydantic import BaseModel,ConfigDict,Field
from .hybrid import Hybrid
from .hybrid_contract import PreviewInput,PlaybackAck
from .hybrid_skills import manifests
from .voice_library import VoiceLibrary
from .story_player import Stories
from .realtime_api import bounded_json
from .models import ID

ROOT=Path(__file__).resolve().parents[3]
class Scoped(BaseModel):
    model_config=ConfigDict(extra='forbid')
    principal:str=Field(pattern=ID)
    client_id:str=Field(pattern=ID)
    binding:str=Field(pattern=ID)
    profile_epoch:str|None=Field(default=None,pattern=ID)
class Open(Scoped):pass
class Operation(Open):conversation_id:str=Field(pattern=ID)
class Dispatch(Scoped):input:PreviewInput
class StoryInput(Operation):
    text:str=Field(default='',max_length=4000)
    title:str=Field(default='',max_length=80)
    fixture:bool=False
class StoryCommand(Scoped):
    action:str=Field(pattern='^(play|pause|resume|stop)$')
class StoryAck(Scoped):ack:PlaybackAck
class SpeechInput(Scoped):
    conversation_id:str=Field(pattern=ID)
    operation_id:str|None=Field(default=None,pattern=ID)
    story_id:str|None=Field(default=None,pattern=ID)
    segment_id:int=Field(default=0,ge=0,le=11)
    paid_consent:bool=False

def attach_brain_hybrid(app,brain,realtime,live,speech,auth,*,policy_path=None):
    policy_path=Path(policy_path or ROOT/'run/night-train/preview-policy.json')
    hybrid=Hybrid(brain);stories=Stories();library=VoiceLibrary();attempts=set();tts_lock=asyncio.Lock()
    app.state.hybrid=hybrid;app.state.stories=stories
    def owned_conversation(ident,scope):
        try:return hybrid.owned(ident,scope)
        except PermissionError:raise HTTPException(403,'preview_scope_or_epoch_expired')
    def owned_story(ident,scope):
        try:return stories.owned(ident,scope)
        except PermissionError:raise HTTPException(403,'story_not_owned_or_expired')
    def allowed(body):
        policy=json.loads(policy_path.read_text()) if policy_path.exists() else {}
        if not policy.get('enabled') or not (realtime.owner_testing.bound(body.binding) or body.binding in policy.get('owner_clients',[])):raise PermissionError('owner_preview_not_enabled_or_bound')
        if body.client_id!=body.binding:raise PermissionError('preview_guest_device_binding_required')
        if body.principal.startswith('personal:'):raise PermissionError('preview_personal_context_not_enabled')
        return (body.principal,body.client_id,body.profile_epoch)
    async def parsed(request,model):
        try:
            body=model.model_validate(await bounded_json(request,16000));scope=allowed(body);return body,scope
        except PermissionError as e:raise HTTPException(403,str(e))
        except ValueError:raise HTTPException(422,'invalid_preview_request')
    @app.post('/api/v1/next/status',dependencies=[Depends(auth)])
    async def status(request:Request):
        body,scope=await parsed(request,Open)
        p=realtime.budget.policy()
        try:
            profile_owner=brain.configuration.devices.scoped_owner(body.principal,body.client_id)
            profile=brain.configuration.devices.profile(profile_owner).model_dump(exclude={'weather'})
        except ValueError:
            from .device_contract import DeviceProfile
            profile=DeviceProfile().model_dump(exclude={'weather'})
        return {'enabled':True,'client_id':scope[1],'runtime_sha':realtime.journal.code_commit,'skills':[s.model_dump() for s in manifests()],
            'profile':profile,
            'provider_sessions_opened':0,'pre_session_router':True,'private_memory':False,'story_new_text_model':'gpt-6-luna',
            'b':{'ready':realtime.budget.active(p) and p.allowed_client_id==body.binding,'model':p.model,'handover':'manual_text_audio_contract','automatic_start':False},
            'c':{'ready':False,'reason':'live_finalization_or_text_handover_not_accepted','billing':live.budget.status()},
            'speech':{'stt':'existing_explicit_consent_route','tts':'existing_manual_adapter','automatic_tts':False,
                'manual_paid_authorized':realtime.owner_testing.authorized(body.binding)},
            'fixture_mode':bool(json.loads(policy_path.read_text()).get('fixture_mode',False))}
    @app.post('/api/v1/next/open',dependencies=[Depends(auth)])
    async def open_conversation(request:Request):
        body,scope=await parsed(request,Open);c=hybrid.open(scope)
        return {'conversation_id':c.id,'profile_epoch':body.profile_epoch,'remember':False}
    @app.post('/api/v1/next/transcribe',dependencies=[Depends(auth)])
    async def transcribe(request:Request,principal:str,client_id:str,binding:str,paid_consent:bool=False):
        try:scope=allowed(Scoped(principal=principal,client_id=client_id,binding=binding))
        except (ValueError,PermissionError):raise HTTPException(403,'owner_preview_required')
        if not paid_consent or not realtime.owner_testing.authorized(binding):raise HTTPException(403,'existing_owner_stt_admission_required')
        if any(not s.closed and s.offer.client_id==client_id for s in [*realtime.sessions.values(),*live.sessions.values()]):raise HTTPException(409,'native_session_already_owns_microphone')
        raw=bytearray()
        async for part in request.stream():
            raw.extend(part)
            if len(raw)>4*1024*1024:raise HTTPException(413,'preview_recording_limit')
        pcm=await speech.decode(bytes(raw),request.headers.get('content-type',''))
        if not 3200<=len(pcm)<=16000*2*15:raise HTTPException(422,'truncated_or_empty_recording_not_transcribed')
        try:realtime.owner_testing.reserve(binding,'realtime','web-stt:'+uuid4().hex,estimate=.5,origin='web_stt')
        except PermissionError as error:raise HTTPException(403,str(error))
        out=io.BytesIO()
        with wave.open(out,'wb') as f:f.setparams((1,2,16000,0,'NONE',''));f.writeframes(pcm)
        try:return await speech.transcribe(out.getvalue(),'audio/wav','openai',paid_consent=True)
        except PermissionError:raise HTTPException(403,'speech_provider_consent_or_policy_denied')
        except Exception:raise HTTPException(502,'speech_transcription_failed')
    @app.post('/api/v1/next/operation',dependencies=[Depends(auth)])
    async def operation(request:Request):
        body,scope=await parsed(request,Operation)
        try:return {'operation_id':hybrid.issue(body.conversation_id,scope)}
        except PermissionError as e:raise HTTPException(403,str(e))
    @app.post('/api/v1/next/dispatch',dependencies=[Depends(auth)])
    async def dispatch(request:Request):
        body,scope=await parsed(request,Dispatch)
        try:return (await hybrid.dispatch(body.input,scope)).model_dump()
        except PermissionError as e:raise HTTPException(403,str(e))
        except ValueError as e:raise HTTPException(409,str(e))
    @app.post('/api/v1/next/timers',dependencies=[Depends(auth)])
    async def timers(request:Request):
        body,scope=await parsed(request,Open);owner=hybrid.tool_owner(scope)
        with brain.memory.connect() as db:
            rows=db.execute("SELECT id,deadline,status FROM timers WHERE device_id=? AND status='running' ORDER BY deadline DESC LIMIT 16",(owner,)).fetchall()
        return {'timers':[dict(r) for r in rows]}
    @app.post('/api/v1/next/library',dependencies=[Depends(auth)])
    async def inventory(request:Request):
        await parsed(request,Open);return await asyncio.to_thread(library.inventory)
    @app.post('/api/v1/next/stories',dependencies=[Depends(auth)])
    async def story(request:Request):
        body,scope=await parsed(request,StoryInput)
        c=owned_conversation(body.conversation_id,scope)
        try:job=stories.create(scope,body.text,body.title,body.fixture)
        except ValueError as e:raise HTTPException(422,str(e))
        c.media='story'
        return job.public()
    @app.post('/api/v1/next/stories/{ident}/command',dependencies=[Depends(auth)])
    async def story_command(ident:str,request:Request):
        body,scope=await parsed(request,StoryCommand)
        try:job=stories.owned(ident,scope)
        except PermissionError:raise HTTPException(403,'story_not_owned')
        if job.state=='stopped' and body.action!='stop':raise HTTPException(409,'story_already_stopped')
        if body.action=='stop':job.epoch+=1;job.state='stopped';job.audio.clear()
        else:job.state='playing' if body.action in {'play','resume'} else 'paused'
        return job.public()
    @app.post('/api/v1/next/stories/{ident}/ack',dependencies=[Depends(auth)])
    async def story_ack(ident:str,request:Request):
        body,scope=await parsed(request,StoryAck)
        try:return stories.ack(stories.owned(ident,scope),body.ack)
        except (PermissionError,ValueError):raise HTTPException(409,'invalid_or_stale_story_ack')
    @app.post('/api/v1/next/stories/{ident}/heard',dependencies=[Depends(auth)])
    async def heard(ident:str,request:Request):
        body,scope=await parsed(request,Open)
        try:return stories.heard_context(stories.owned(ident,scope))
        except PermissionError:raise HTTPException(403,'story_not_owned')
    @app.post('/api/v1/next/stories/{ident}/audio/{segment}',dependencies=[Depends(auth)])
    async def story_audio(ident:str,segment:int,request:Request):
        body,scope=await parsed(request,Open)
        try:
            job=stories.owned(ident,scope)
            if not 0<=segment<len(job.segments):raise ValueError()
            if job.state=='stopped':raise HTTPException(409,'story_stopped')
            if job.fixture:raw=stories.fixture_audio(job,segment)
            else:
                raw=job.audio.get(str(segment))
                if raw is None:raise HTTPException(409,'story_audio_missing_manual_tts_required')
            return Response(raw,media_type='audio/wav',headers={'Cache-Control':'no-store'})
        except PermissionError:raise HTTPException(403,'story_not_owned')
        except ValueError:raise HTTPException(422,'invalid_story_audio')
    @app.post('/api/v1/next/speech',dependencies=[Depends(auth)])
    async def manual_speech(request:Request):
        body,scope=await parsed(request,SpeechInput)
        if not body.paid_consent or not realtime.owner_testing.authorized(body.binding):raise HTTPException(403,'explicit_manual_tts_consent_required')
        if any(not s.closed and s.offer.client_id==scope[1] for s in [*realtime.sessions.values(),*live.sessions.values()]):raise HTTPException(409,'close_native_audio_before_tts')
        owned_conversation(body.conversation_id,scope)
        job=None
        if body.story_id:
            job=owned_story(body.story_id,scope)
            if job.fixture:raise HTTPException(409,'fixture_uses_local_test_audio')
            if not 0<=body.segment_id<len(job.segments):raise HTTPException(422,'invalid_story_segment')
            text=job.segments[body.segment_id];key=job.id+':'+str(body.segment_id)
            if job.state=='stopped':raise HTTPException(409,'story_stopped')
        else:
            op=hybrid.operations.get(body.operation_id)
            if not op or op['scope']!=scope or op['conversation']!=body.conversation_id or not op['result']:raise HTTPException(403,'verified_answer_required')
            text=op['result'].answer.speech_text;key=body.operation_id
        if len(text)>1000:raise HTTPException(422,'manual_speech_text_limit')
        if key in attempts:raise HTTPException(409,'speech_already_attempted_no_automatic_retry')
        if len(attempts)>=256:raise HTTPException(429,'preview_speech_capacity')
        if tts_lock.locked():raise HTTPException(409,'one_preview_synthesis_at_a_time')
        if sum(len(raw) for story in stories.jobs.values() for raw in story.audio.values())>28*1024*1024:raise HTTPException(429,'temporary_story_audio_capacity')
        async with tts_lock:return await synthesize(body,scope,request,text,key,job)
    async def synthesize(body,scope,request,text,key,job):
        attempts.add(key)
        # Existing Owner API allowance; no new quota, separate origin, pending until actual usage is known.
        try:realtime.owner_testing.reserve(body.binding,'realtime','web-tts:'+key,estimate=.5,origin='web_tts')
        except PermissionError as e:raise HTTPException(403,str(e))
        chunks=[];rate=24000;size=0;epoch=job.epoch if job else None
        generator=speech.synthesize(text,'openai','marin',paid_consent=True)
        try:
            async for chunk,rate in generator:
                if await request.is_disconnected() or job and (job.epoch!=epoch or job.state in {'stopped','paused'}):raise asyncio.CancelledError()
                size+=len(chunk)
                if size>24000*2*60:raise ValueError('manual_speech_audio_limit')
                chunks.append(chunk)
        finally:await generator.aclose()
        if not chunks:raise HTTPException(502,'speech_provider_returned_no_audio')
        if job and (job.epoch!=epoch or job.state in {'stopped','paused'}):raise asyncio.CancelledError()
        out=io.BytesIO()
        with wave.open(out,'wb') as f:f.setparams((1,2,rate,0,'NONE',''));f.writeframes(b''.join(chunks))
        raw=out.getvalue()
        if job:job.audio[str(body.segment_id)]=raw;job.durations[str(body.segment_id)]=size/2/rate
        return Response(raw,media_type='audio/wav',headers={'Cache-Control':'no-store'})
    @app.post('/api/v1/next/stories/generate',dependencies=[Depends(auth)])
    async def generate_story(request:Request):
        body,scope=await parsed(request,SpeechInput)
        if not body.paid_consent:raise HTTPException(403,'explicit_manual_text_generation_consent_required')
        owned_conversation(body.conversation_id,scope)
        op=hybrid.operations.get(body.operation_id)
        if not op or op['scope']!=scope or op['conversation']!=body.conversation_id or not op['result'] or op['result'].route_type!='START_STORYTELLER':raise HTTPException(403,'story_operation_required')
        parts=[]
        async def text(part):parts.append(part)
        try:
            result=await live.backend.answer(op['text'],{},binding=body.binding,operation=body.operation_id+':story',on_text=text)
            job=stories.create(scope,''.join(parts),'Новая история · gpt-6-luna');hybrid.owned(body.conversation_id,scope).media='story'
            return {**job.public(),'provider_result':result}
        except PermissionError as e:raise HTTPException(403,str(e))

def attach_gateway_hybrid(app,settings,devices,subject,device_scope):
    auth={'Authorization':'Bearer '+settings.api_token}
    def json_response(result):
        try:body=result.json()
        except ValueError:return JSONResponse({'detail':'preview_backend_invalid_response'},status_code=502)
        return JSONResponse(body,status_code=result.status_code)
    async def identity(request):
        guest='browser-'+request.client.host.replace('.','-')
        profile=await asyncio.to_thread(devices.profile,device_scope(request,guest))
        # New preview is explicitly guest-context even if the browser has a PIN cookie.
        return {'principal':guest,'client_id':profile.client_id,'binding':profile.client_id,'profile_epoch':None}
    async def forward(request,path,body=None,binary=False):
        scope=await identity(request)
        payload={**(body or {}),**scope}
        async with httpx.AsyncClient(trust_env=False,timeout=55) as client:
            result=await client.post('http://127.0.0.1:18781/api/v1/next/'+path,headers=auth,json=payload)
        if binary:return Response(result.content,status_code=result.status_code,media_type=result.headers.get('content-type','application/octet-stream'))
        return json_response(result)
    @app.get('/device-next')
    async def preview(request:Request):
        check=await forward(request,'status')
        if check.status_code!=200:return check
        return FileResponse(ROOT/'services/phone/dist/device-next.html',media_type='text/html')
    @app.get('/api/next/status')
    async def status(request:Request):return await forward(request,'status')
    @app.post('/api/next/transcribe')
    async def transcribe(request:Request,paid_consent:bool=False):
        raw=bytearray()
        async for part in request.stream():
            raw.extend(part)
            if len(raw)>4*1024*1024:raise HTTPException(413,'preview_recording_limit')
        scope=await identity(request);scope.pop('profile_epoch');scope['paid_consent']=str(paid_consent).lower()
        async with httpx.AsyncClient(trust_env=False,timeout=55) as client:
            result=await client.post('http://127.0.0.1:18781/api/v1/next/transcribe',headers={**auth,'Content-Type':request.headers.get('content-type','')},params=scope,content=bytes(raw))
        return json_response(result)
    @app.post('/api/next/{path:path}')
    async def api(path:str,request:Request):
        if path not in {'open','operation','dispatch','timers','library','stories','speech','stories/generate'} and not __import__('re').fullmatch(r'stories/[a-f0-9]{32}/(?:command|ack|heard|audio/\d{1,2})',path):raise HTTPException(404)
        body=await bounded_json(request,12000)
        if set(body)&{'principal','client_id','binding','profile_epoch','approved','role','budget'}:raise HTTPException(422,'client_authority_fields_denied')
        return await forward(request,path,body,binary=path=='speech' or '/audio/' in path)
