import asyncio,json
from fastapi import Depends,HTTPException,Request
from .processes import AgentError

async def bounded(request,limit=8192):
    raw=bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw)>limit:raise HTTPException(413,'request_too_large')
    return bytes(raw)

def attach_family(app,family,identity,speech,auth):
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
