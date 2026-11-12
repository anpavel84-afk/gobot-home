"""Owner-bound diagnostic read/delete over the existing authenticated gateway."""
import asyncio
import re
import httpx
from fastapi import Depends,HTTPException,Request
from fastapi.responses import JSONResponse


def attach_brain_journal(app,manager,auth):
    journal=manager.journal
    def scope(device_id,client_id,profile_epoch,binding):
        if not manager.owner_testing.bound(binding):raise HTTPException(403,'owner_device_required')
        return journal.scope(device_id,client_id,profile_epoch or None)

    @app.get('/api/v1/debug-journal',dependencies=[Depends(auth)])
    async def sessions(device_id:str,client_id:str,binding:str,profile_epoch:str=''):
        key=scope(device_id,client_id,profile_epoch,binding)
        await journal.flush()
        return {'status':journal.status(binding),'sessions':await asyncio.to_thread(journal.sessions,key)}

    @app.get('/api/v1/debug-journal/{session}',dependencies=[Depends(auth)])
    async def read(session:str,device_id:str,client_id:str,binding:str,profile_epoch:str='',before:int|None=None):
        key=scope(device_id,client_id,profile_epoch,binding)
        if not re.fullmatch(r'[a-zA-Z0-9_.:-]{1,100}',session) or before is not None and not 1<=before<2**63:raise HTTPException(422,'journal_query_invalid')
        await journal.flush()
        return await asyncio.to_thread(journal.read,key,session,before=before)

    @app.post('/api/v1/debug-journal/clear',dependencies=[Depends(auth)])
    async def clear(request:Request):
        from .realtime_api import bounded_json
        body=await bounded_json(request,2000)
        if set(body)-{'device_id','client_id','binding','profile_epoch','session_id'}:raise HTTPException(422,'journal_clear_invalid')
        key=scope(body.get('device_id'),body.get('client_id'),body.get('profile_epoch'),body.get('binding'))
        session=body.get('session_id')
        if session is not None and not re.fullmatch(r'[a-zA-Z0-9_.:-]{1,100}',str(session)):raise HTTPException(422,'journal_query_invalid')
        await journal.flush()
        return {'deleted':await asyncio.to_thread(journal.clear,key,session)}


def attach_gateway_journal(app,settings,devices,subject,device_scope,profile_epoch):
    base='http://127.0.0.1:18781/api/v1/debug-journal'
    auth={'Authorization':'Bearer '+settings.api_token}
    async def identity(request):
        owner=await subject(request)
        profile=await asyncio.to_thread(devices.profile,device_scope(request,owner))
        guest='browser-'+request.client.host.replace('.','-')
        bound=await asyncio.to_thread(devices.profile,device_scope(request,guest))
        return {'device_id':owner,'client_id':profile.client_id,'profile_epoch':profile_epoch(request,owner) or '', 'binding':bound.client_id}
    async def forward(method,url,*,params=None,body=None):
        async with httpx.AsyncClient(trust_env=False,timeout=8) as client:
            result=await client.request(method,url,headers=auth,params=params,json=body)
        return JSONResponse(result.json(),status_code=result.status_code,headers={'Cache-Control':'no-store'})

    @app.get('/api/debug-journal')
    async def sessions(request:Request):return await forward('GET',base,params=await identity(request))

    @app.get('/api/debug-journal/{session}')
    async def read(session:str,request:Request,before:int|None=None):
        if not re.fullmatch(r'[a-zA-Z0-9_.:-]{1,100}',session):raise HTTPException(422,'journal_query_invalid')
        params=await identity(request)
        if before is not None:params['before']=before
        return await forward('GET',base+'/'+session,params=params)

    @app.post('/api/debug-journal/clear')
    async def clear(request:Request):
        from .realtime_api import bounded_json
        body=await bounded_json(request,2000)
        if set(body)-{'session_id'}:raise HTTPException(422,'journal_clear_invalid')
        return await forward('POST',base+'/clear',body={**body,**await identity(request)})
