import asyncio, hmac, json, time, re
from contextlib import asynccontextmanager
from fastapi import FastAPI,Request,HTTPException,Depends,WebSocket,WebSocketDisconnect
from fastapi.responses import StreamingResponse
from .models import ChatRequest,VoiceRequest,event
from .memory import Memory,Conflict
from .providers import fast_stream,bridge_stream,SentenceBuffer,MockAgentAdapter,cancellable,merge_presentation
from .processes import AgentError
from .live_agents import agent_status
from .audio import Speech
from .pipeline import voiced_events
from .family import Family
from .speaker import SpeakerIdentity
from .family_api import attach_family
from .routing import SmartRouter
from .context_manager import ContextManager
from .quality import Assessment,SelectiveVerifier
from .local_tools import LocalTools,text_stream
from .visual import VisualService
from .visual_images import ImageCache
from pathlib import Path
from .presentation_planner import MultimodalResponsePlanner
from .response_composer import VisualResponseComposer
from .telemetry import Traces,Trace,scope,mark,client_trace,CURRENT

class Service:
    def __init__(self,settings):
        self.presentation_planner=MultimodalResponsePlanner()
        self.composer=VisualResponseComposer(self.presentation_planner)
        self.active_voice_streams=0
        self.traces=Traces(Path(settings.db).parent)
        self.settings=settings;self.memory=Memory(settings.db);self.running={};self.limit=asyncio.Semaphore(4);self.router=SmartRouter(settings.router);self.context_manager=ContextManager.configured();self.tools=LocalTools(self.memory);self.verifier=SelectiveVerifier();self.visual=VisualService(cache=ImageCache(Path(settings.db).parent/'visual-cache'))
    async def prepare(self,req):
        try:return await asyncio.to_thread(self.memory.start,req)
        except Conflict as e:raise HTTPException(409,str(e))
    async def events(self,req,replay=None):
        if replay:
            try:
                for entry in json.loads(replay.get('trace') or '[]'):
                    if entry.get('presentation'):
                        frame=self.visual.replay(entry['presentation'])
                        if frame.type=='timer_widget' and frame.metadata.timer_id:
                            with self.memory.connect() as c:timer=c.execute('SELECT status FROM timers WHERE id=? AND device_id=?',(frame.metadata.timer_id,req.device_id)).fetchone()
                            if not timer or timer[0]=='cancelled':frame.metadata.state='cancelled';frame.metadata.deadline=None;frame.text='Таймер остановлен.';frame.actions=[]
                        yield event(req,'visual_response',presentation=frame.model_dump(),replayed=True)
            except (ValueError,TypeError):pass
            yield event(req,'final' if replay['status']=='completed' else replay['status'] if replay['status'] in {'cancelled','error'} else 'error',text=replay['result'],provider=replay['provider'],replayed=True);return
        cancel=asyncio.Event();self.running[req.turn_id]=cancel;state='cancelled';text='';provider='unselected' if req.mode not in {None,'mock'} else 'mock';trace=[];started=time.perf_counter();first=None;buffer=SentenceBuffer();acquired=False;iterator=None;visual_task=None
        try:
            mark("brain_queue_start")
            try:await asyncio.wait_for(self.limit.acquire(),0.1);acquired=True;mark("brain_queue_end")
            except TimeoutError:
                state='error';yield event(req,'error',code='busy');return
            async with asyncio.timeout(self.settings.timeout):
                mark("context_start")
                ctx=await asyncio.to_thread(self.memory.context,req)
                mark("context_end")
                decision=None;widget=None;selected=req.mode;verification=None;must_gate=False;spoken_override=None;visual_frame=None
                if req.mode is not None or req.provider in {'codex','antigravity','google','gemini'}:
                    request_for_route=req if req.mode is not None else req.model_copy(update={'mode':req.provider})
                    mark("admission_start")
                    admission=await asyncio.to_thread(agent_status,req.usage_consent)
                    mark("admission_end")
                    decision=self.router.choose(request_for_route,ctx,admission)
                    mark("router_end",route=decision.category,model=decision.model,concurrency=len(self.running))
                    ctx=self.context_manager.pack(req.text,ctx,'DETAILED' if req.context_detail=='detailed' else decision.category)
                    if req.remember:await asyncio.to_thread(self.memory.archive.record_context,req,ctx,decision.provider)
                    mark("context_pack_end",context_tokens=ctx.get("_context_meta",{}).get("packet_tokens"))
                    route=decision.category;provider=('bridge:'+decision.provider) if decision.provider in {'codex','antigravity'} else decision.provider
                    second=decision.reason=='explicit_model_selection';trace=[decision.public()]
                    source_req=req.model_copy(update={'provider':decision.provider,'model_id':decision.model}) if decision.provider in {'codex','antigravity'} else req
                    if ctx.get('topic',{}).get('outcome')=='ambiguous':source=text_stream('Уточни, к какой теме или прошлому разговору ты хочешь вернуться. Подходящий источник пока не найден.');provider='local'
                    elif decision.provider=='local' and decision.tool=='visual':
                        yield event(req,'tool_status',status='loading_visual',route='TOOL',provider='local',reason=decision.reason,model=None)
                        initial_plan=self.composer.plan(req,route=decision,context=ctx)
                        visual_work=self.visual.attachment(req,initial_plan,timeout=18) if initial_plan.visual_strategy=='generate' else self.visual.handle(req,active_turns=len(self.running))
                        work=asyncio.create_task(visual_work);stop=asyncio.create_task(cancel.wait())
                        try:
                            done,_=await asyncio.wait({work,stop},timeout=.35,return_when=asyncio.FIRST_COMPLETED)
                            if not done:
                                yield event(req,'sentence_ready',text='Подбираю визуальный материал.',representation='progress')
                                done,_=await asyncio.wait({work,stop},return_when=asyncio.FIRST_COMPLETED)
                            if stop in done:raise asyncio.CancelledError()
                            result=work.result();visual_frame=result.frame;spoken_override=result.speech_text;source=text_stream(result.display_text)
                            verification={'accepted':True,'method':'image_source_metadata' if visual_frame.images else 'explicit_availability_state','fact_confirmed':False}
                        finally:
                            work.cancel();stop.cancel();await asyncio.gather(work,stop,return_exceptions=True)
                    elif decision.provider=='local':
                        tool_result=await asyncio.to_thread(self.tools.execute,decision.tool,req);widget=tool_result.widget
                        verification=self.verifier.check(Assessment(**decision.quality),tool_result.text,tool_result.evidence)
                        source=text_stream(tool_result.text if verification['accepted'] else 'Не удалось подтвердить ответ по доступным данным. Я не буду выдавать предположение за факт.')
                        if widget and widget.get('payload',{}).get('timer_id'):visual_frame=self.visual.timer(req,widget)
                        elif decision.tool=='verification' and self.visual.intent.detect(req.text):visual_frame=self.visual.fallback(req,'Нужна проверка','verification_unavailable',kind='status_card',text=tool_result.text).frame
                    elif decision.provider=='mock':source=MockAgentAdapter().stream(req.text,ctx)
                    else:source=bridge_stream(self.settings,source_req,ctx)
                    must_gate=bool(decision.quality.get('verification_required') and decision.provider not in {'local','mock'})
                else:
                    # Explicit legacy diagnostics retain the original fixture API contract.
                    ctx=self.context_manager.pack(req.text,ctx,'FAST_CHAT')
                    route=req.route if req.route!='auto' else ('agent' if 'задач' in req.text.lower() else 'fast')
                    second=bool(re.search(r'спроси\s+(chatgpt|gemini|cursor)',req.text,re.I))
                    provider='bridge:mock' if route=='agent' else ('openai' if req.provider!='mock' and self.settings.fast_provider=='openai' and self.settings.api_key else 'mock')
                    trace=[{'route':route,'reason':'explicit_second_opinion' if second else 'request_or_fast_default'}]
                    if req.remember:await asyncio.to_thread(self.memory.archive.record_context,req,ctx,provider)
                    source=bridge_stream(self.settings,req,ctx) if route=='agent' else fast_stream(self.settings,req,ctx)
                yield event(req,'tool_status',status='running',route=route,provider=provider,second_opinion=second,model=decision.model if decision else None,reason=decision.reason if decision else trace[0]['reason'],billing_kind=decision.billing_kind if decision else 'diagnostic',router_ms=decision.router_ms if decision else None,quality=decision.quality if decision else None,verification=verification,topic=ctx.get('topic'),context=ctx.get('_context_meta'))
                presentation_plan=self.composer.plan(req,route=decision,context=ctx)
                if decision:yield event(req,'screen_scene',scene=self.composer.compose(req,route=decision,context=ctx,plan=presentation_plan).model_dump(exclude={'display_text','speech_text'}),phase='planning')
                if decision:trace.append({'presentation_plan':presentation_plan.model_dump()})
                if decision and not visual_frame and presentation_plan.visual_needed and presentation_plan.origin=='implicit':
                    visual_task=asyncio.create_task(self.visual.attachment(req,presentation_plan,timeout=self.presentation_planner.policy.helpful_timeout_seconds))
                    yield event(req,'tool_status',status='preparing_visual_attachment',presentation_plan=presentation_plan.model_dump())
                if visual_frame:
                    yield event(req,'visual_response',presentation=visual_frame.model_dump())
                    trace.append({'presentation':visual_frame.model_dump()})
                try:
                    iterator=merge_presentation(cancellable(source,cancel),visual_task,cancel)
                    async for kind,delta in iterator:
                        if kind=='visual_failed':
                            trace.append({'optional_visual_error':'attachment_unavailable'});continue
                        if kind=='visual':
                            yield event(req,'visual_response',presentation=delta.frame.model_dump(),attachment=True)
                            trace.append({'presentation':delta.frame.model_dump()});continue
                        if kind=='text_done':
                            if not must_gate and spoken_override is None:
                                for sentence in buffer.feed('',final=True):yield event(req,'sentence_ready',text=sentence)
                                yield event(req,'tool_status',status='speech_input_complete')
                            continue
                        if first is None:first=(time.perf_counter()-started)*1000;mark("first_assistant_delta")
                        text+=delta
                        if len(text)>32000:raise ValueError('Output limit')
                        if not must_gate:
                            yield event(req,'text_delta',text=delta)
                            if spoken_override is None:
                                for sentence in buffer.feed(delta):yield event(req,'sentence_ready',text=sentence)
                except asyncio.CancelledError:raise
                except Exception as error:
                    if not req.expensive_fallback_approved or not req.usage_consent or text or provider=='bridge:codex':raise
                    if iterator is not None:await iterator.aclose()
                    provider='bridge:codex';trace.append({'fallback':'codex','reason':error.code if isinstance(error,AgentError) else 'antigravity_unavailable'})
                    if decision:
                        from dataclasses import replace
                        decision=replace(decision,provider='codex',model='gpt-6.1-sol',reason='approved_expensive_fallback')
                    yield event(req,'tool_status',status='fallback',provider=provider,reason=trace[-1]['reason'])
                    source_req=req.model_copy(update={'provider':'codex','model_id':'gpt-6.1-sol'})
                    iterator=cancellable(bridge_stream(self.settings,source_req,ctx),cancel)
                    async for delta in iterator:
                        if first is None:first=(time.perf_counter()-started)*1000;mark("first_assistant_delta")
                        text+=delta
                        if len(text)>32000:raise AgentError('output_limit')
                        if not must_gate:
                            yield event(req,'text_delta',text=delta)
                            for sentence in buffer.feed(delta):yield event(req,'sentence_ready',text=sentence)
                if must_gate:
                    verification=self.verifier.check(Assessment(**decision.quality),text,None)
                    if not verification['accepted']:text='Не удалось подтвердить ответ по доступным данным. Я не буду выдавать предположение за факт.'
                    yield event(req,'text_delta',text=text)
                    for sentence in buffer.feed(text):yield event(req,'sentence_ready',text=sentence)
                if decision:trace.append({'verification':verification or {'method':'not_required'}})
                if spoken_override is not None:
                    if spoken_override:yield event(req,'sentence_ready',text=spoken_override,representation='speech')
                else:
                    for sentence in buffer.feed('',final=True):yield event(req,'sentence_ready',text=sentence)
                if widget:
                    yield event(req,'widget_command',command=widget,mock=False)
                elif (decision is None or decision.provider=='mock') and 'таймер' in req.text.lower():
                    yield event(req,'widget_command',command={'type':'custom','payload':{'namespace':'gobot.ui','version':1,'command':'timer.start','duration_ms':300000}},mock=True)
                if decision:trace.append({'usage':ctx.get('_provider_usage'),'billing_kind':decision.billing_kind,'model':decision.model})
                if decision:
                    scene=self.composer.compose(req,route=decision,context=ctx,plan=presentation_plan,answer=text.strip(),has_visual=any('presentation' in item for item in trace))
                    yield event(req,'screen_scene',scene=scene.model_dump(exclude={'display_text','speech_text'}),phase='answer_complete');trace.append({'screen_scene':scene.model_dump(exclude={'display_text','speech_text'})})
                state='completed'
                await asyncio.to_thread(self.memory.finish,req,state,text.strip(),provider,trace)
                if req.remember:await asyncio.to_thread(self.memory.archive.record_usage,req,ctx.get('_provider_usage'),ctx.get('_provider_session_id'))
                yield event(req,'final',text=text.strip(),provider=provider,trace=trace,presentation_plan=presentation_plan.model_dump(),llm_first_token_ms=first,total_ms=(time.perf_counter()-started)*1000,mock=provider.startswith('mock') or provider=='bridge:mock',model=decision.model if decision else None,bridge_telemetry=ctx.get('_bridge_telemetry'),usage=ctx.get('_provider_usage'),billing_kind=decision.billing_kind if decision else 'diagnostic',router_ms=decision.router_ms if decision else None,quality=decision.quality if decision else None,verification=verification)
        except TimeoutError:
            state='error';yield event(req,'error',code='timeout')
        except asyncio.CancelledError:
            state='cancelled'
            if asyncio.current_task().cancelling():raise
            # On socket disconnect there is no receiver; persistence is still finalized below.
            yield event(req,'cancelled',code='interrupted')
        except GeneratorExit:raise
        except AgentError as error:
            state='error';trace.append({'error_code':error.code});yield event(req,'error',code=error.code)
        except Exception:
            state='error';yield event(req,'error',code='provider_failed')
        finally:
            if iterator is not None:await iterator.aclose()
            if visual_task is not None:
                visual_task.cancel();await asyncio.gather(visual_task,return_exceptions=True)
            self.running.pop(req.turn_id,None)
            if acquired:self.limit.release()
            # synchronous short final transaction survives task cancellation
            self.memory.finish(req,state,text.strip(),provider,trace)
            self.memory.record_metrics(req.turn_id,provider,{'llm_first_token':first,'total_text':(time.perf_counter()-started)*1000})
            if req.remember and not getattr(self,'maintenance',None):
                self.maintenance=asyncio.create_task(asyncio.to_thread(self.memory.archive.maintain_one))
                self.maintenance.add_done_callback(lambda _:setattr(self,'maintenance',None))

def create_app(settings=None):
    if settings is None:
        from .config import load
        settings=load()
    settings.validate();service=Service(settings);speech=Speech();family=Family(service.memory);identity=SpeakerIdentity(family)
    @asynccontextmanager
    async def lifespan(app):
        await asyncio.to_thread(service.memory.recover)
        await asyncio.to_thread(agent_status) # Metadata/hash warmup only; admission still rechecks per request.
        yield
        for flag in service.running.values():flag.set()
        await identity.close()
    app=FastAPI(lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None);app.state.service=service
    async def auth(request:Request):
        if not hmac.compare_digest(request.headers.get('authorization',''),'Bearer '+settings.api_token):raise HTTPException(401,'Authentication required')
    attach_family(app,family,identity,speech,auth)
    @app.get('/healthz')
    async def health():return {'status':'ok','service':'gobot-brain'}
    @app.get('/readyz')
    async def ready():
        await asyncio.to_thread(service.memory.status,'readiness');return {'ready':True,'mode':'mock' if settings.fast_provider=='mock' else 'configured','voice_hardware_ready':False}
    @app.get('/api/v1/status',dependencies=[Depends(auth)])
    async def status():return {'active_turns':len(service.running),'active_voice_streams':service.active_voice_streams,'voice':speech.status(),'agents':await asyncio.to_thread(agent_status),'real_e2e_verified':False,'visual':{**service.visual.available(),'presentation_policy':service.presentation_planner.policy.model_dump()},'speaker_identity':{'installed':identity.engine.installed(),'calibrated':bool(await asyncio.to_thread(family.calibration)),'experimental':True}}
    @app.get('/api/v1/visual/assets/{asset}/{variant}.jpg',dependencies=[Depends(auth)])
    async def visual_asset(asset:str,variant:str):
        from fastapi import Response
        try:data,record=await asyncio.to_thread(service.visual.cache.read,asset,variant)
        except (KeyError,OSError):raise HTTPException(404,'image_expired_or_missing')
        return Response(data,media_type='image/jpeg',headers={'Content-Length':str(len(data)),'X-Content-Type-Options':'nosniff','Cache-Control':'private, max-age=300'})
    @app.post('/api/v1/visual/timer/cancel',dependencies=[Depends(auth)])
    async def cancel_visual_timer(request:Request):
        body=await request.json();owner=body.get('device_id');ident=body.get('timer_id')
        if not isinstance(owner,str) or not isinstance(ident,str) or not re.fullmatch(r'[a-f0-9-]{36}',ident):raise HTTPException(422)
        def update():
            with service.memory.connect() as c:return c.execute("UPDATE timers SET status='cancelled' WHERE id=? AND device_id=?",(ident,owner)).rowcount
        if not await asyncio.to_thread(update):raise HTTPException(404,'timer_not_found_or_not_owned')
        return {'cancelled':True,'timer_id':ident}
    @app.get('/api/v1/timers',dependencies=[Depends(auth)])
    async def active_timers(device_id:str):
        if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,100}',device_id):raise HTTPException(422)
        with service.memory.connect() as c:rows=c.execute("SELECT id,deadline,status FROM timers WHERE device_id=? AND status='running' AND deadline>? ORDER BY deadline LIMIT 16",(device_id,time.time())).fetchall()
        return {'timers':[dict(row) for row in rows]}
    @app.get('/api/v1/history/{conversation_id}',dependencies=[Depends(auth)])
    async def history(conversation_id:str,device_id:str):
        return await asyncio.to_thread(service.memory.history,conversation_id,device_id)
    @app.get('/api/v1/metrics',dependencies=[Depends(auth)])
    async def metrics():return {'stages':await asyncio.to_thread(service.memory.metric_summary),'first_physical_audio_measured':False}
    @app.get('/api/v1/memory',dependencies=[Depends(auth)])
    async def memory_state(device_id:str,conversation_id:str):
        return await asyncio.to_thread(service.memory.archive.inspect,device_id,conversation_id)
    @app.get('/api/v1/memory/source/{message_id}',dependencies=[Depends(auth)])
    async def memory_source(message_id:int,device_id:str):
        result=await asyncio.to_thread(service.memory.archive.source,device_id,message_id)
        if not result:raise HTTPException(404)
        return result
    @app.post('/api/v1/memory',dependencies=[Depends(auth)])
    async def memory_change(request:Request):
        from pydantic import BaseModel,Field,ConfigDict
        class Change(BaseModel):
            model_config=ConfigDict(extra='forbid')
            device_id:str=Field(pattern=r'^[A-Za-z0-9_.:-]{1,100}$')
            action:str
            id:str=Field(max_length=100)
            content:str=Field(default='',max_length=2000)
        try:change=Change.model_validate(await request.json())
        except ValueError:raise HTTPException(422,'invalid_memory_change')
        archive=service.memory.archive
        if change.action in {'delete_fact','revise_fact'} and change.id.isdigit():
            ok=await asyncio.to_thread(archive.revise_fact,change.device_id,int(change.id),change.content if change.action=='revise_fact' and change.content.strip() else None)
        elif change.action=='rename_topic' and change.content.strip():ok=await asyncio.to_thread(archive.rename_topic,change.device_id,change.id,change.content)
        elif change.action=='forget_conversation':ok=await asyncio.to_thread(archive.forget_conversation,change.device_id,change.id)
        else:raise HTTPException(422,'invalid_memory_action')
        if not ok:raise HTTPException(404,'memory_item_not_found_or_not_owned')
        return {'updated':True}
    @app.post('/api/v1/audio/playback',dependencies=[Depends(auth)])
    async def playback(request:Request):
        body=await request.json()
        if not isinstance(body,dict) or not all(isinstance(body.get(k),str) and len(body[k])<=100 for k in ('device_id','turn_id','segment_id')):raise HTTPException(422)
        value=body.get('milliseconds',0)
        if not isinstance(value,(int,float)) or not __import__('math').isfinite(value):raise HTTPException(422)
        await asyncio.to_thread(service.memory.archive.playback,body['device_id'],body['turn_id'],body['segment_id'],value)
        return {'recorded':True,'source':'untrusted_client_telemetry_not_acoustic_proof'}
    @app.post('/api/v1/audio/transcribe',dependencies=[Depends(auth)])
    async def transcribe(request:Request,provider:str='openai',paid_consent:bool=False,device_id:str='local-test',trace_id:str|None=None,trace_owner:str|None=None):
        trace=service.traces.get(trace_owner or device_id,trace_id or 'upload');trace.mark('stt_upload_first')
        data=bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data)>8*1024*1024:raise HTTPException(413,'audio_too_large')
        trace.mark("stt_upload_last",input_bytes=len(data),stt_mode=provider)
        # Launch local decoding/identity and STT together; never await identity before STT.
        job=identity.submit_recording(bytes(data),request.headers.get('content-type',''),speech,device_id)
        try:
            with scope(trace):result=await speech.transcribe(bytes(data),request.headers.get('content-type',''),provider,paid_consent=paid_consent)
            trace.mark('stt_final');result['telemetry']=trace.snapshot();await asyncio.to_thread(service.traces.save,trace_owner or device_id,trace)
            result['speaker_job_id']=job
            result['speaker']=identity.result(job,device_id) if job else {'state':'unknown','reason':'identity_pending','personal_authorized':False}
            await asyncio.to_thread(service.memory.record_metrics,job or 'upload',result.get('provider',provider),{'stt_final':result.get('stt_ms')})
            return result
        except AgentError as error:raise HTTPException(422,error.code)
        except Exception:raise HTTPException(503,'stt_unavailable')
    @app.post('/api/v1/telemetry',dependencies=[Depends(auth)])
    async def telemetry_post(request:Request):
        raw=await request.body()
        if len(raw)>16384:raise HTTPException(413)
        try:
            body=json.loads(raw);owner=body.pop('device_id');sample=client_trace(body)
            if not isinstance(owner,str) or len(owner)>100:raise ValueError()
        except (ValueError,KeyError,TypeError):raise HTTPException(422)
        await asyncio.to_thread(service.traces.save,owner,sample);return {'recorded':True}
    @app.get('/api/v1/telemetry/{ident}',dependencies=[Depends(auth)])
    async def telemetry_get(ident:str,device_id:str):return {'traces':await asyncio.to_thread(service.traces.read,device_id,ident)}
    @app.get('/api/v1/speaker/{job}',dependencies=[Depends(auth)])
    async def speaker_result(job:str,device_id:str):return identity.result(job,device_id)
    @app.websocket('/api/v1/audio/live')
    async def live_stt(ws:WebSocket):
        if not hmac.compare_digest(ws.headers.get('authorization',''),'Bearer '+settings.api_token):
            await ws.close(code=4401);return
        await ws.accept();iterator=None;trace=None;token=None
        try:
            config=json.loads(await asyncio.wait_for(ws.receive_text(),5))
            if config.get('provider','openai')!='openai':raise AgentError('live_stt_requires_openai')
            pcm=bytearray();device_id=str(config.get('device_id','local-test'))[:100];job=None
            trace=service.traces.get(device_id,str(config.get('trace_id') or 'live')[:100]);trace.mark('live_connected',stt_mode='openai-live');token=CURRENT.set(trace)
            def start_identity():
                nonlocal job
                if job is not None:return
                import numpy as np
                samples=np.frombuffer(bytes(pcm),dtype='<i2')
                converted=np.interp(np.arange(0,len(samples),1.5),np.arange(len(samples)),samples).astype('<i2').tobytes()
                job=identity.submit(converted,device_id)
            async def chunks():
                async with asyncio.timeout(65):
                    while True:
                        message=await ws.receive()
                        if message['type']=='websocket.disconnect':raise asyncio.CancelledError()
                        if message.get('text'):
                            if message['text']=='end':
                                start_identity();return
                            raise AgentError('invalid_audio_message')
                        raw=message.get('bytes',b'');pcm.extend(raw)
                        if len(pcm)>2880000:raise AgentError('audio_too_large')
                        if job is None and len(pcm)>=288000:start_identity()
                        yield raw
            from .stt import OpenAIRecognition
            iterator=OpenAIRecognition().live(chunks(),paid_consent=config.get('paid_consent') is True)
            async for item in iterator:
                if item['type']=='stt_final':
                    trace.mark('stt_final');item['data']['telemetry']=trace.snapshot()
                    item['data']['speaker_job_id']=job
                    item['data']['speaker']=identity.result(job,device_id) if job else {'state':'unknown','reason':'identity_pending','personal_authorized':False}
                    await asyncio.to_thread(service.memory.record_metrics,job or 'live','openai-live',{
                        'stt_first_interim':item['data'].get('first_interim_ms'),'stt_final':item['data'].get('final_ms'),
                        'speech_end_to_stt_final':item['data'].get('speech_end_to_final_ms')})
                await ws.send_json(item)
        except (WebSocketDisconnect,asyncio.CancelledError):pass
        except AgentError as error:
            with __import__('contextlib').suppress(Exception):await ws.send_json({'type':'error','data':{'code':error.code}})
        except Exception:
            with __import__('contextlib').suppress(Exception):await ws.send_json({'type':'error','data':{'code':'live_stt_unavailable'}})
        finally:
            if iterator:await iterator.aclose()
            if trace:await asyncio.to_thread(service.traces.save,device_id,trace)
            if token is not None:CURRENT.reset(token)
            with __import__('contextlib').suppress(Exception):await ws.close()
    @app.post('/api/v1/chat/voice/stream',dependencies=[Depends(auth)])
    async def voice_stream(req:VoiceRequest,request:Request):
        chat_req=ChatRequest.model_validate(req.model_dump(exclude={'speak','tts_provider','tts_voice','paid_tts_consent','speaker_job_id'}))
        trace=service.traces.get(chat_req.device_id,chat_req.trace_id or chat_req.utterance_id or chat_req.turn_id);trace.mark("memory_prepare_start")
        replay=await service.prepare(chat_req)
        trace.mark("memory_prepare_end")
        async def generate():
            iterator=voiced_events(service,speech,chat_req,speak=req.speak,tts_provider=req.tts_provider,tts_voice=req.tts_voice,paid_tts_consent=req.paid_tts_consent,replay=replay,prepared=True)
            try:
                async for item in iterator:
                    if item['type']=='audio_chunk':trace.mark('audio_transport_send')
                    if item['type']=='final':item['data']['telemetry']=trace.snapshot()
                    yield 'event: '+item['type']+'\ndata: '+json.dumps(item,ensure_ascii=False)+'\n\n'
            finally:await iterator.aclose()
        return StreamingResponse(generate(),media_type='text/event-stream',headers={'Cache-Control':'no-store','X-Accel-Buffering':'no'})
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
