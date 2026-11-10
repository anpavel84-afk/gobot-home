import asyncio,json
from fastapi import Depends,HTTPException,Request
from .processes import AgentError

async def bounded(request,limit=8192):
    raw=bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw)>limit:raise HTTPException(413,'request_too_large')
    return bytes(raw)

def attach_family(app,family,identity,speech,auth,*,on_preferences_changed=None,openings=None):
    async def body(request):
        try:
            obj=json.loads(await bounded(request))
            if not isinstance(obj,dict):raise ValueError()
            return obj
        except ValueError:raise HTTPException(422,'invalid_family_request')
    @app.get('/api/v1/family',dependencies=[Depends(auth)])
    async def profiles():
        return {'profiles':await asyncio.to_thread(family.profiles),'calibration':await asyncio.to_thread(family.calibration),
                'model_installed':identity.engine.installed(),'biometrics_cloud_upload':False,'personal_history_requires_pin':True}
    @app.post('/api/v1/family',dependencies=[Depends(auth)])
    async def create(request:Request):
        data=await body(request)
        try:return await asyncio.to_thread(family.create,data.get('name'),data.get('age'),data.get('pin'),data.get('avatar',''),data.get('consent',False),data.get('parent_consent',False))
        except ValueError as error:raise HTTPException(422,str(error))
    @app.post('/api/v1/family/login',dependencies=[Depends(auth)])
    async def login(request:Request):
        data=await body(request)
        try:return await asyncio.to_thread(family.verify_pin,data.get('profile_id'),data.get('pin'))
        except ValueError:raise HTTPException(403,'invalid_profile_or_pin')
    @app.post('/api/v1/family/session',dependencies=[Depends(auth)])
    async def valid(request:Request):
        data=await body(request)
        return {'valid':await asyncio.to_thread(family.session_valid,data.get('id'),data.get('epoch',''))}
    @app.get('/api/v1/family/voices',dependencies=[Depends(auth)])
    async def voices():
        from .family_preferences import voice_catalog
        return {'voices':await asyncio.to_thread(voice_catalog,openings),'custom_voice_creation':False,'preview_paid_synthesis':False}
    @app.post('/api/v1/family/{ident}/preferences',dependencies=[Depends(auth)])
    async def preferences(ident:str,request:Request):
        data=await body(request)
        if set(data)-{'operation','actor_id','actor_epoch','preferences','expected_revision'}:raise HTTPException(422,'unknown_preference_field')
        actor,epoch=data.get('actor_id'),data.get('actor_epoch');operation=data.get('operation')
        try:
            await asyncio.to_thread(family.preferences.authorize,ident,actor,epoch,write=operation in {'update','reset'})
            if operation in {'read','inspect'}:
                value=await asyncio.to_thread(family.preferences.get,ident)
                value.update(speaker_status='unknown_until_local_observation',private_voice_access=False,selection='manual_pin_confirmed',applies='next_eligible_realtime_session')
                return value
            if operation=='update':value=await asyncio.to_thread(family.preferences.update,ident,data.get('preferences'),data.get('expected_revision'),actor,epoch)
            elif operation=='reset':value=await asyncio.to_thread(family.preferences.reset,ident,data.get('expected_revision'),actor,epoch)
            else:raise ValueError('invalid_preference_operation')
            if on_preferences_changed:await on_preferences_changed('personal:'+ident,'preferences_changed')
            return value
        except PermissionError as error:raise HTTPException(403,str(error))
        except KeyError:raise HTTPException(404,'family_profile_not_found')
        except ValueError:raise HTTPException(409,'invalid_preferences_or_revision_conflict')
    @app.post('/api/v1/family/calibrate',dependencies=[Depends(auth)])
    async def calibrate():
        try:return await asyncio.to_thread(family.calibrate)
        except ValueError as error:raise HTTPException(422,str(error))
    @app.post('/api/v1/family/fact',dependencies=[Depends(auth)])
    async def fact(request:Request):
        data=await body(request);scope=data.get('scope_id');text=data.get('text')
        if not isinstance(scope,str) or not (scope=='family:home' or scope.startswith('personal:')) or not isinstance(text,str) or not 1<=len(text.strip())<=500 or data.get('consent') is not True:raise HTTPException(422,'explicit_fact_consent_required')
        await asyncio.to_thread(family.memory.add_fact,scope,text.strip(),True)
        return {'saved':True,'scope':'family' if scope=='family:home' else 'personal'}
    @app.delete('/api/v1/family/unknown',dependencies=[Depends(auth)])
    async def unknown_delete():
        await asyncio.to_thread(family.reset_voice,None);return {'unknown_biometric_samples_deleted':True}
    @app.post('/api/v1/family/{ident}/enable',dependencies=[Depends(auth)])
    async def enable(ident:str,request:Request):
        data=await body(request)
        try:await asyncio.to_thread(family.enable,ident,data.get('enabled') is True)
        except ValueError as error:raise HTTPException(422,str(error))
        return {'updated':True,'calibration_required':True}
    @app.delete('/api/v1/family/{ident}/voice',dependencies=[Depends(auth)])
    async def reset(ident:str):
        await asyncio.to_thread(family.reset_voice,ident);return {'biometrics_deleted':True}
    @app.delete('/api/v1/family/{ident}',dependencies=[Depends(auth)])
    async def delete(ident:str):
        if on_preferences_changed:await on_preferences_changed('personal:'+ident,'profile_deleted')
        await asyncio.to_thread(family.delete,ident);return {'profile_and_personal_memory_deleted':True}
    @app.post('/api/v1/family/{ident}/sample',dependencies=[Depends(auth)])
    async def sample(ident:str,request:Request,kind:str='enroll'):
        if kind not in {'enroll','validation','unknown'}:raise HTTPException(422,'invalid_sample_kind')
        if request.query_params.get('sample_consent')!='true':raise HTTPException(403,'sample_consent_required')
        raw=await bounded(request,8*1024*1024)
        try:
            pcm=await speech.decode(raw,request.headers.get('content-type',''))
            return await identity.enroll(None if kind=='unknown' else ident,pcm,kind)
        except (AgentError,ValueError) as error:raise HTTPException(422,str(error))
