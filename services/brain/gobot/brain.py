import asyncio, hmac, json, time, re
from contextlib import asynccontextmanager
from fastapi import FastAPI,Request,HTTPException,Depends
from fastapi.responses import StreamingResponse
from .models import ChatRequest,event
from .memory import Memory,Conflict
from .providers import fast_stream,bridge_stream,SentenceBuffer,MockAgentAdapter,cancellable

class Service:
    def __init__(self,settings):
        self.settings=settings;self.memory=Memory(settings.db);self.running={};self.limit=asyncio.Semaphore(4)
    async def prepare(self,req):
        try:return await asyncio.to_thread(self.memory.start,req)
        except Conflict as e:raise HTTPException(409,str(e))
    async def events(self,req,replay=None):
        if replay:
            yield event(req,'final' if replay['status']=='completed' else replay['status'] if replay['status'] in {'cancelled','error'} else 'error',text=replay['result'],provider=replay['provider'],replayed=True);return
        cancel=asyncio.Event();self.running[req.turn_id]=cancel;state='cancelled';text='';provider='mock';trace=[];started=time.perf_counter();first=None;buffer=SentenceBuffer();acquired=False;iterator=None
        try:
            try:await asyncio.wait_for(self.limit.acquire(),0.1);acquired=True
            except TimeoutError:
                state='error';yield event(req,'error',code='busy');return
            async with asyncio.timeout(self.settings.timeout):
                ctx=await asyncio.to_thread(self.memory.context,req)
                route=req.route if req.route!='auto' else ('agent' if req.provider in {'codex','cursor','gemini'} or 'задач' in req.text.lower() else 'fast')
                second=bool(re.search(r'спроси\s+(chatgpt|gemini|cursor)',req.text,re.I))
                trace=[{'route':route,'reason':'explicit_second_opinion' if second else 'request_or_fast_default'}]
                if second and 'chatgpt' in req.text.lower():route='fast';trace[0]['route']='fast'
                provider=('bridge:'+('mock' if req.provider=='auto' else req.provider)) if route=='agent' else ('openai' if req.provider!='mock' and self.settings.fast_provider=='openai' and self.settings.api_key else 'mock')
                source_req=req
                if second:
                    target=re.search(r'спроси\s+(chatgpt|gemini|cursor)',req.text,re.I).group(1).lower()
                    trace[0]['requested_provider']=target
                    if target in {'gemini','cursor'}:
                        route='agent';trace[0]['route']='agent';source_req=req.model_copy(update={'provider':target});provider='bridge:'+target
                    elif req.provider!='mock':source_req=req.model_copy(update={'provider':'openai'})
                source=bridge_stream(self.settings,source_req,ctx) if route=='agent' else fast_stream(self.settings,source_req,ctx)
                yield event(req,'tool_status',status='running',route=route,provider=provider,second_opinion=second)
                try:
                    iterator=cancellable(source,cancel)
                    async for delta in iterator:
                        if first is None:first=(time.perf_counter()-started)*1000
                        text+=delta
                        if len(text)>32000:raise ValueError('Output limit')
                        yield event(req,'text_delta',text=delta)
                        for sentence in buffer.feed(delta):yield event(req,'sentence_ready',text=sentence)
                except asyncio.CancelledError:raise
                except Exception:
                    if text:raise
                    trace.append({'fallback':'mock','reason':'provider_unavailable_or_policy_blocked'});provider='mock:fallback'
                    yield event(req,'tool_status',status='fallback',reason='provider_unavailable_or_policy_blocked')
                    async for delta in MockAgentAdapter().stream(req.text,ctx):
                        if cancel.is_set():raise asyncio.CancelledError()
                        if first is None:first=(time.perf_counter()-started)*1000
                        text+=delta;yield event(req,'text_delta',text=delta)
                        for sentence in buffer.feed(delta):yield event(req,'sentence_ready',text=sentence)
                for sentence in buffer.feed('',final=True):yield event(req,'sentence_ready',text=sentence)
                if 'таймер' in req.text.lower():
                    yield event(req,'widget_command',command={'type':'custom','payload':{'namespace':'gobot.ui','version':1,'command':'timer.start','duration_ms':300000}},mock=True)
                state='completed'
                await asyncio.to_thread(self.memory.finish,req,state,text.strip(),provider,trace)
                yield event(req,'final',text=text.strip(),provider=provider,trace=trace,llm_first_token_ms=first,total_ms=(time.perf_counter()-started)*1000,mock=provider!='openai')
        except TimeoutError:
            state='error';yield event(req,'error',code='timeout')
        except asyncio.CancelledError:
            state='cancelled'
            # On socket disconnect there is no receiver; persistence is still finalized below.
            yield event(req,'cancelled',code='interrupted')
        except GeneratorExit:raise
        except Exception:
            state='error';yield event(req,'error',code='provider_failed')
        finally:
            if iterator is not None:await iterator.aclose()
            self.running.pop(req.turn_id,None)
            if acquired:self.limit.release()
            # synchronous short final transaction survives task cancellation
            self.memory.finish(req,state,text.strip(),provider,trace)

def create_app(settings=None):
    if settings is None:
        from .config import load
        settings=load()
    settings.validate();service=Service(settings)
    @asynccontextmanager
    async def lifespan(app):
        await asyncio.to_thread(service.memory.recover);yield
        for flag in service.running.values():flag.set()
    app=FastAPI(lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None);app.state.service=service
    async def auth(request:Request):
        if not hmac.compare_digest(request.headers.get('authorization',''),'Bearer '+settings.api_token):raise HTTPException(401,'Authentication required')
    @app.get('/healthz')
    async def health():return {'status':'ok','service':'gobot-brain'}
    @app.get('/readyz')
    async def ready():
        await asyncio.to_thread(service.memory.status,'readiness');return {'ready':True,'mode':'mock' if settings.fast_provider=='mock' else 'configured','voice_hardware_ready':False}
    @app.get('/api/v1/status',dependencies=[Depends(auth)])
    async def status():return {'mode':'configured-api' if settings.fast_provider=='openai' and settings.api_key and settings.allow_paid else 'mock','active_turns':len(service.running),'voice':{'runtime':'fixture-only','asr':settings.asr,'tts':settings.tts,'vad':settings.vad,'real_speech_ready':False},'real_agents_enabled':False}
    @app.get('/api/v1/turns/{turn_id}',dependencies=[Depends(auth)])
    async def turn_status(turn_id:str):
        result=await asyncio.to_thread(service.memory.status,turn_id)
        if result is None:raise HTTPException(404)
        return result
    @app.post('/api/v1/turns/{turn_id}/cancel',dependencies=[Depends(auth)])
    async def cancel(turn_id:str):
        if turn_id in service.running:service.running[turn_id].set()
        return {'turn_id':turn_id,'cancel_requested':True}
    @app.post('/api/v1/chat/stream',dependencies=[Depends(auth)])
    async def stream(req:ChatRequest,request:Request):
        replay=await service.prepare(req)
        async def generate():
            iterator=service.events(req,replay)
            try:
                async for item in iterator:
                    if await request.is_disconnected():break
                    yield 'event: '+item.type+'\ndata: '+item.model_dump_json()+'\n\n'
            finally:await iterator.aclose()
        return StreamingResponse(generate(),media_type='text/event-stream',headers={'Cache-Control':'no-store','X-Accel-Buffering':'no'})
    @app.post('/api/v1/chat',dependencies=[Depends(auth)])
    async def chat(req:ChatRequest):
        replay=await service.prepare(req);items=[]
        async for item in service.events(req,replay):items.append(item.model_dump())
        return {'events':items}
    return app
