import asyncio,json
from contextlib import asynccontextmanager
from fastapi import FastAPI,Request,HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel,ConfigDict,Field
from .security import Verifier,sign_event
from .providers import MockAgentAdapter
from .live_agents import live_stream, agent_status
from .processes import AgentError
from .models import ExecutorModel
from .telemetry import Trace,scope,CURRENT,mark
class Task(BaseModel):
    model_config=ConfigDict(extra='forbid')
    text:str=Field(min_length=1,max_length=8000)
    provider:str='mock'
    context:dict=Field(default_factory=dict)
    turn_id:str=Field(max_length=100)
    usage_consent:bool=False
    model_id:ExecutorModel|None=None
    trace_id:str|None=Field(default=None,max_length=100)

def create_app(settings=None):
    if settings is None:
        from .config import load
        settings=load()
    @asynccontextmanager
    async def lifespan(app):
        await asyncio.to_thread(agent_status) # No CLI/model request; warm local verified hashes.
        try:yield
        finally:
            from .antigravity_acp import shutdown
            await shutdown()
    app=FastAPI(lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None);verifier=Verifier(settings.bridge_secret);semaphore=asyncio.Semaphore(2)
    @app.get('/healthz')
    async def health():return {'status':'ok','service':'host-agent-bridge','admission':'isolation-and-request-consent'}
    @app.post('/v1/stream')
    async def stream(request:Request):
        if request.client and request.client.host not in {'127.0.0.1','testclient'}:raise HTTPException(403,'Local only')
        if int(request.headers.get('content-length','0'))>131072:raise HTTPException(413)
        body=await request.body()
        if len(body)>131072:raise HTTPException(413)
        nonce=verifier.verify(request.headers,body)
        try:task=Task.model_validate_json(body)
        except ValueError:raise HTTPException(422,'Invalid task')
        if task.provider not in {'mock','auto','codex','antigravity'}:raise HTTPException(403,'Provider denied')
        if task.provider in {'codex','antigravity'} and not task.usage_consent:raise HTTPException(403,'quota_consent_required')
        trace=Trace(task.trace_id or task.turn_id,"bridge");trace.mark("bridge_queue_start")
        try:await asyncio.wait_for(semaphore.acquire(),0.1)
        except TimeoutError:raise HTTPException(429,'Bridge busy')
        async def generate():
            seq=0;token=CURRENT.set(trace);trace.mark("bridge_queue_end")
            try:
                async with asyncio.timeout(settings.timeout):
                    usage={}
                    source = MockAgentAdapter().stream(task.text,task.context) if task.provider in {'mock','auto'} else live_stream(task.provider,task.text,task.context,usage_consent=task.usage_consent,model_id=task.model_id,usage=usage,antigravity_transport=settings.router.antigravity_transport)
                    async for delta in source:
                        yield json.dumps(sign_event(settings.bridge_secret,nonce,seq,{'type':'text_delta','text':delta}),ensure_ascii=False)+'\n';seq+=1
                    yield json.dumps(sign_event(settings.bridge_secret,nonce,seq,{"type":"telemetry","trace":trace.snapshot()}))+"\n";seq+=1
                    if usage:
                        yield json.dumps(sign_event(settings.bridge_secret,nonce,seq,{'type':'usage','usage':usage,'billing_kind':'cli_subscription'}))+'\n';seq+=1
                    if task.context.get('_provider_session_id'):
                        yield json.dumps(sign_event(settings.bridge_secret,nonce,seq,{'type':'session','session_id':task.context['_provider_session_id']}))+'\n';seq+=1
                    yield json.dumps(sign_event(settings.bridge_secret,nonce,seq,{'type':'final'}))+'\n'
            except TimeoutError:
                yield json.dumps(sign_event(settings.bridge_secret,nonce,seq,{'type':'error','code':'timeout'}))+'\n'
            except AgentError as error:
                trace.mark('failed',code=error.code)
                yield json.dumps(sign_event(settings.bridge_secret,nonce,seq,{'type':'telemetry','trace':trace.snapshot()}))+'\n';seq+=1
                yield json.dumps(sign_event(settings.bridge_secret,nonce,seq,{'type':'error','code':error.code}))+'\n'
            except Exception:
                yield json.dumps(sign_event(settings.bridge_secret,nonce,seq,{'type':'error','code':'agent_execution_failed'}))+'\n'
            finally:semaphore.release();CURRENT.reset(token)
        return StreamingResponse(generate(),media_type='application/x-ndjson')
    return app
