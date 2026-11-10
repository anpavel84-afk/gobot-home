import asyncio,json
from fastapi import FastAPI,Request,HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel,ConfigDict,Field
from .security import Verifier,sign_event
from .providers import MockAgentAdapter
class Task(BaseModel):
    model_config=ConfigDict(extra='forbid')
    text:str=Field(min_length=1,max_length=8000)
    provider:str='mock'
    context:dict=Field(default_factory=dict)
    turn_id:str=Field(max_length=100)

def create_app(settings=None):
    if settings is None:
        from .config import load
        settings=load()
    app=FastAPI(docs_url=None,redoc_url=None,openapi_url=None);verifier=Verifier(settings.bridge_secret);semaphore=asyncio.Semaphore(2)
    @app.get('/healthz')
    async def health():return {'status':'ok','mode':'mock','real_agents_enabled':False}
    @app.post('/v1/stream')
    async def stream(request:Request):
        if request.client and request.client.host not in {'127.0.0.1','testclient'}:raise HTTPException(403,'Local only')
        if int(request.headers.get('content-length','0'))>65536:raise HTTPException(413)
        body=await request.body()
        if len(body)>65536:raise HTTPException(413)
        nonce=verifier.verify(request.headers,body)
        try:task=Task.model_validate_json(body)
        except ValueError:raise HTTPException(422,'Invalid task')
        # No HTTP field can enable real CLI execution. Host containment has not been verified.
        if task.provider not in {'mock','auto'}:raise HTTPException(403,'Real CLI disabled: containment and owner integration approval required')
        try:await asyncio.wait_for(semaphore.acquire(),0.1)
        except TimeoutError:raise HTTPException(429,'Bridge busy')
        async def generate():
            seq=0
            try:
                async with asyncio.timeout(settings.timeout):
                    async for delta in MockAgentAdapter().stream(task.text,task.context):
                        yield json.dumps(sign_event(settings.bridge_secret,nonce,seq,{'type':'text_delta','text':delta}),ensure_ascii=False)+'\n';seq+=1
                    yield json.dumps(sign_event(settings.bridge_secret,nonce,seq,{'type':'final'}))+'\n'
            except TimeoutError:
                yield json.dumps(sign_event(settings.bridge_secret,nonce,seq,{'type':'error','code':'timeout'}))+'\n'
            finally:semaphore.release()
        return StreamingResponse(generate(),media_type='application/x-ndjson')
    return app
