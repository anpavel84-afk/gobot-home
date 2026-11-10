"""Experimental ACP candidate. Off by default and denied without native proof.

Reuses GoBot's bounded stdio RPC and Windows kill-on-close job. No credentials
are read here, no resume/load, no permission grants and no transport retries.
"""
import asyncio,hashlib,json,time,weakref
from pathlib import Path
from .agents import AppServerTransport
from .antigravity import ROOT,POLICY,WORK,argv,environment,binary
from .processes import AgentError,native_process
from .telemetry import mark

def launch_argv():
    # Confirmed in the installed 1.5.3 help. Never add skip-permissions flags.
    return argv(stream=False)+['acp','--sandbox','--process-per-session','--disable-telemetry']

def admitted():
    try:
        proof=json.loads((ROOT/'run/antigravity-acp-audit.json').read_text())
        expected={'binary_sha256':hashlib.sha256(binary().read_bytes()).hexdigest(),
                  'policy_sha256':hashlib.sha256(POLICY.read_bytes()).hexdigest(),
                  'adapter_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
        return all(proof.get(k)==v for k,v in expected.items()) and all(proof.get(k) is True for k in
            ['native_session_deny_verified','no_permission_bypass','adversarial_tool_execution_checked'])
    except (OSError,ValueError,TypeError,AttributeError,AgentError):return False

class AcpRPC(AppServerTransport):
    async def send(self,obj):await super().send({'jsonrpc':'2.0',**obj})

class AcpRuntime:
    """One serialized runtime, max 16 fresh sessions; no family-wide thread."""
    def __init__(self,process_factory=native_process):
        self.factory=process_factory;self.cm=None;self.rpc=None;self.consumer=None
        self.lock=asyncio.Lock();self.updates=asyncio.Queue(maxsize=32)
        self.session=None;self.capabilities={};self.used=0;self.failure=None;self.idle=None;self.sessions=set();self.activity=0
    async def open(self):
        if self.rpc:return
        self.failure=None;self.cm=self.factory(launch_argv(),WORK,environment())
        process=await self.cm.__aenter__()
        self.rpc=AcpRPC(process.stdout,process.stdin,timeout=10);await self.rpc.start()
        self.consumer=asyncio.create_task(self.dispatch())
        try:
            result=await self.rpc.request('initialize',{'protocolVersion':1,
                'clientInfo':{'name':'gobot_home','version':'0.1'},
                'clientCapabilities':{'fs':{'readTextFile':False,'writeTextFile':False},'terminal':False}})
            if result.get('protocolVersion')!=1:raise AgentError('acp_protocol_version')
            self.capabilities=result.get('agentCapabilities',{})
        except BaseException:await self.close();raise
    async def dispatch(self):
        try:
            async for obj in self.rpc.events():
                method=obj.get('method');params=obj.get('params',{})
                if 'id' in obj and method:
                    if method=='session/request_permission':
                        await self.rpc.reply(obj['id'],{'outcome':{'outcome':'cancelled'}})
                    else:await self.rpc.reply(obj['id'],error={'code':-32601,'message':'GoBot denies client tools'})
                    self.failure='acp_tool_request_denied'
                    continue
                if method!='session/update' or params.get('sessionId')!=self.session:continue
                update=params.get('update',{})
                if update.get('sessionUpdate') in {'tool_call','tool_call_update'}:
                    self.failure='acp_tool_activity_denied';continue
                if update.get('sessionUpdate') in {'agent_message_chunk','usage_update'}:
                    self.updates.put_nowait(update)
        except asyncio.CancelledError:raise
        except Exception:self.failure='acp_protocol_or_queue_error'
        finally:
            self.failure=self.failure or 'acp_runtime_disconnected'
    async def new_session(self):
        result=await self.rpc.request('session/new',{'cwd':str(WORK.resolve()),'mcpServers':[]})
        session=result.get('sessionId')
        if not isinstance(session,str) or not 1<=len(session)<=200 or session in self.sessions:raise AgentError('acp_invalid_session')
        self.sessions.add(session)
        self.session=session;self.used+=1;return result
    async def end_session(self):
        if not self.rpc or not self.session:return
        session=self.session;self.session=None
        caps=self.capabilities.get('sessionCapabilities',{})
        if 'close' not in caps:await self.close();return
        try:await asyncio.wait_for(self.rpc.request('session/close',{'sessionId':session}),2)
        except Exception:await self.close()
    async def close(self):
        if self.idle:self.idle.cancel();self.idle=None
        if self.consumer:self.consumer.cancel();await asyncio.gather(self.consumer,return_exceptions=True);self.consumer=None
        if self.rpc:await self.rpc.close();self.rpc=None
        if self.cm:await self.cm.__aexit__(None,None,None);self.cm=None
        self.session=None;self.used=0;self.sessions.clear()
    async def stream(self,prompt,context,model_id):
        try:await asyncio.wait_for(self.lock.acquire(),.1)
        except TimeoutError:raise AgentError('acp_queue_busy')
        request=None;complete=False;self.activity+=1;self.idle.cancel() if self.idle else None;self.idle=None
        try:
            async with asyncio.timeout(90):
                if self.used>=16:await self.close()
                await self.open()
                if self.failure:raise AgentError(self.failure)
                while not self.updates.empty():self.updates.get_nowait()
                mark('acp_session_start');session=await self.new_session();mark('acp_session_ready')
                # Selection only from the native session's advertised registry.
                models=session.get('models',{});available=models.get('availableModels',[])
                if model_id and models.get('currentModelId')!=model_id:
                    if not any(row.get('modelId')==model_id for row in available):raise AgentError('acp_model_unavailable')
                    await self.rpc.request('session/set_model',{'sessionId':self.session,'modelId':model_id})
                context['_provider_session_id']=self.session
                self.rpc.timeout=85
                request=asyncio.create_task(self.rpc.request('session/prompt',{'sessionId':self.session,'prompt':[{'type':'text','text':prompt}]}))
                mark('prompt_sent',transport='antigravity_acp');first_deadline=time.monotonic()+35;seen=False
                while True:
                    if self.failure:raise AgentError(self.failure)
                    if request.done():
                        await asyncio.sleep(0) # Drain preceding notifications before completion.
                        if self.updates.empty() and self.rpc.queue.empty():break
                    try:update=await asyncio.wait_for(self.updates.get(),.05)
                    except TimeoutError:
                        if not seen and time.monotonic()>first_deadline:raise AgentError('acp_first_output_timeout')
                        continue
                    if update.get('sessionUpdate')=='usage_update':
                        raw=update.get('usage',{})
                        context['_acp_usage']={k:v for k,v in raw.items() if k in {'inputTokens','outputTokens','totalTokens'} and type(v) is int and v>=0}
                    else:
                        content=update.get('content',{});text=content.get('text')
                        if content.get('type')=='text' and isinstance(text,str) and text:
                            seen=True;mark('assistant_delta');yield text
                result=await request
                if result.get('stopReason')!='end_turn':raise AgentError('acp_incomplete_turn')
                complete=True
        finally:
            if not complete and self.rpc and self.session:
                try:await asyncio.wait_for(self.rpc.notify('session/cancel',{'sessionId':self.session}),1)
                except Exception:pass
            if request and not request.done():request.cancel();await asyncio.gather(request,return_exceptions=True)
            if complete:
                if self.rpc:self.rpc.timeout=10
                await self.end_session()
            else:await self.close() # Never reuse an uncertain or cancelled runtime.
            self.lock.release()
            if self.rpc:
                activity=self.activity
                self.idle=asyncio.get_running_loop().call_later(60,lambda:asyncio.create_task(self.close_if_idle(activity)))
    async def close_if_idle(self,activity):
        if self.lock.locked() or activity!=self.activity:return
        async with self.lock:
            if activity==self.activity:await self.close()

_pools=weakref.WeakKeyDictionary()
def pool():
    loop=asyncio.get_running_loop()
    if loop not in _pools:_pools[loop]=AcpRuntime()
    return _pools[loop]
async def shutdown():
    runtime=_pools.pop(asyncio.get_running_loop(),None)
    if runtime:await runtime.close()

class AntigravityACPAdapter:
    def __init__(self):self.usage=None
    async def stream(self,text,context,model_id=None):
        if not admitted():raise AgentError('acp_isolation_not_verified')
        from .live_agents import context_prompt
        async for delta in pool().stream(context_prompt(text,context),context,model_id):yield delta
        self.usage=context.get('_acp_usage') # Missing counters remain unavailable.
