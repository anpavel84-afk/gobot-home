"""Optional loopback authenticated board-B routes, never a second Brain.

Explicit attachment is required in a later accepted deployment. No browser policy
write, Owner approval, arbitrary text command or model fallback is exposed here.
"""
import asyncio,json
from fastapi import Depends,HTTPException,Request
from fastapi.responses import StreamingResponse
from .realtime_api import bounded_json
from .realtime_contract import RealtimeOffer,RealtimeCommand

def attach_board_realtime(app,manager,auth):
    base='/api/v1/voice-ab/b'
    def owned(ident,device):
        if device!=manager.budget.policy().allowed_client_id:raise HTTPException(403,'exact_board_required')
        try:return manager.owned(ident,device,device,None)
        except KeyError:raise HTTPException(404,'board_session_not_found')

    @app.get(base+'/status',dependencies=[Depends(auth)])
    async def status():
        state=manager.budget.board_status()
        state['active_sessions']=sum(not s.closed for s in manager.sessions.values())
        active={s.call_id for s in manager.sessions.values() if not s.closed}
        unresolved=[call for call in await asyncio.to_thread(manager.budget.pending_calls) if call not in active]
        state['pending_hangups']=len(unresolved)
        state['admission_reason']='board_previous_hangup_unconfirmed' if unresolved else None if state['enabled'] and state['sessions_remaining'] else 'board_budget_disabled_or_exhausted'
        state['enabled']=state['enabled'] and state['sessions_remaining']>0 and not unresolved
        return state

    @app.post(base+'/sessions',dependencies=[Depends(auth)])
    async def create(request:Request):
        try:return await manager.start(RealtimeOffer.model_validate(await bounded_json(request)))
        except PermissionError as error:raise HTTPException(403,str(error))
        except ValueError:raise HTTPException(409,'invalid_or_busy_board_session')
        except Exception:raise HTTPException(502,'board_setup_failed_no_retry')

    @app.post(base+'/sessions/{ident}/command',dependencies=[Depends(auth)])
    async def command(ident:str,request:Request):
        data=await bounded_json(request,2000);device=data.pop('device_id',None)
        # No client-supplied identity/profile epoch or privileged command extension.
        try:cmd=RealtimeCommand.model_validate(data)
        except ValueError:raise HTTPException(422,'invalid_board_command')
        if device!=manager.budget.policy().allowed_client_id:raise HTTPException(403,'exact_board_required')
        if cmd.action=='close':return await manager.close(ident,device,device,None,cmd.close_reason or 'user_stop')
        s=owned(ident,device)
        try:
            if cmd.action=='followup' and s.current is None:await s.listen_initial();return {'accepted':True}
            if cmd.action not in {'followup','playback_started','playback_stopped','interrupt'}:raise ValueError()
            return await s.command(cmd)
        except ValueError:raise HTTPException(409,'board_playback_or_input_not_ready')

    @app.get(base+'/sessions/{ident}/events',dependencies=[Depends(auth)])
    async def events(ident:str,request:Request,device_id:str):
        s=owned(ident,device_id)
        if s.subscriber:raise HTTPException(409,'board_subscriber_exists')
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
                await manager.close(ident,device_id,device_id,None,'client_events_disconnected')
        return StreamingResponse(generate(),media_type='text/event-stream',headers={'Cache-Control':'no-store'})
