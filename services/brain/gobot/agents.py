"""Structured CLI adapters. Live execution is not exposed by the host Bridge.
Parsers and JSON-RPC lifecycle are usable with fixture transports without spending quota.
"""
from .telemetry import mark
import asyncio,json,os,signal
from pathlib import Path
from .security import redact
from .processes import AgentError,failure_code

class NDJSON:
    def __init__(self):self.buffer=b''
    def feed(self,data,final=False):
        self.buffer+=data
        if len(self.buffer)>262144:raise ValueError('JSON record too large')
        lines=self.buffer.split(b'\n');self.buffer=lines.pop();out=[]
        for line in lines:
            if line.strip():out.append(json.loads(line))
        if final and self.buffer.strip():out.append(json.loads(self.buffer));self.buffer=b''
        return out

class CursorAdapter:
    def __init__(self,partial=True):self.partial=partial;self.text='';self.completed=False
    @staticmethod
    def argv(executable,prompt,workspace):
        return [executable,'--print','--output-format','stream-json','--stream-partial-output','--mode','ask','--sandbox','enabled','--workspace',str(workspace),'--',prompt]
    def parse(self,obj):
        if self.completed:return []
        kind=obj.get('type');delta=''
        if kind=='assistant':
            msg=obj.get('message',{})
            if msg.get('role')!='assistant':return []
            if self.partial and ('timestamp_ms' not in obj or obj.get('model_call_id') is not None):return []
            delta=''.join(c.get('text','') for c in msg.get('content',[]) if c.get('type')=='text')
        elif kind=='result':
            if obj.get('is_error') or obj.get('subtype')!='success':raise RuntimeError('Cursor failed')
            result=obj.get('result','')
            if result.startswith(self.text):delta=result[len(self.text):]
            elif not self.text:delta=result
            elif result!=self.text:raise ValueError('Cursor final text mismatch')
            self.completed=True
        if delta:self.text+=delta;return [redact(delta)]
        return []

class GeminiCLIAdapter:
    def __init__(self):self.text='';self.completed=False;self.error_code=None
    @staticmethod
    def argv(executable,prompt):return [executable,'-p',prompt,'--output-format','stream-json']
    def parse(self,obj):
        if self.completed:return []
        if obj.get('type')=='error':self.error_code=failure_code(obj);return []
        if obj.get('type')=='result':
            self.completed=True
            if obj.get('status') not in {'success',None}:raise AgentError(self.error_code or failure_code(obj))
            return []
        if obj.get('type')!='message' or obj.get('role')!='assistant':return []
        content=obj.get('content','')
        if not isinstance(content,str):return []
        if obj.get('delta') is True:delta=content
        elif content.startswith(self.text):delta=content[len(self.text):]
        else:delta=content if not self.text else ''
        self.text+=delta;return [redact(delta)] if delta else []

class CodexEventAdapter:
    def __init__(self):self.text='';self.items={};self.completed=False
    def parse(self,obj):
        if self.completed:return []
        kind=obj.get('type');method=obj.get('method');delta=''
        if method=='item/agentMessage/delta':delta=obj.get('params',{}).get('delta','')
        elif kind=='item.completed':
            item=obj.get('item',{})
            if item.get('type')=='agent_message':
                key=item.get('id','default');full=item.get('text','');old=self.items.get(key,'')
                delta=full[len(old):] if full.startswith(old) else '';self.items[key]=full
        elif kind=='turn.failed' or method=='error':raise AgentError(failure_code(obj))
        elif kind=='turn.completed' or method=='turn/completed':
            if method and obj.get('params',{}).get('turn',{}).get('status') not in {'completed',None}:raise AgentError(failure_code(obj))
            self.completed=True
        if delta:self.text+=delta;return [redact(delta)]
        return []

class CodexAppServerAdapter:
    """Wire JSON-RPC over stdio: no jsonrpc field, unlike MCP envelope.
    rpc object provides request(method,params), notify(method,params), events(), reply().
    All approval requests are declined. Runtime transport admission remains disabled.
    """
    def __init__(self,rpc,workspace):self.rpc=rpc;self.workspace=str(Path(workspace).resolve());self.thread_id=None;self.turn_id=None;self.usage=None
    async def initialize(self):
        result=await self.rpc.request('initialize',{'clientInfo':{'name':'gobot_home','title':'GoBot Home','version':'0.1.0'},'capabilities':{'experimentalApi':False}})
        await self.rpc.notify('initialized',{});return result
    async def thread(self,resume=None):
        params={'cwd':self.workspace,'approvalPolicy':'on-request','sandbox':'read-only'}
        if resume:params['threadId']=resume
        else:params['ephemeral']=True
        result=await self.rpc.request('thread/resume' if resume else 'thread/start',params)
        self.thread_id=result['thread']['id'];return self.thread_id
    async def interrupt(self):
        if self.thread_id and self.turn_id:await self.rpc.request('turn/interrupt',{'threadId':self.thread_id,'turnId':self.turn_id})
    async def stream(self,text):
        mark("prompt_dispatch_start")
        result=await self.rpc.request('turn/start',{'threadId':self.thread_id,'input':[{'type':'text','text':text,'text_elements':[]}],'approvalPolicy':'on-request','sandboxPolicy':{'type':'readOnly'}})
        mark('prompt_sent');self.turn_id=result['turn']['id'];parser=CodexEventAdapter()
        try:
            async for obj in self.rpc.events():
                mark("raw_event")
                if obj.get('method')=='thread/tokenUsage/updated':
                    raw=obj.get('params',{}).get('tokenUsage',{}).get('last',{})
                    self.usage={k:v for k,v in raw.items() if k in {'inputTokens','outputTokens','totalTokens','cachedInputTokens','reasoningOutputTokens'} and isinstance(v,int) and v>=0}
                    continue
                if 'id' in obj and 'method' in obj:
                    method=obj['method']
                    if method in {'item/commandExecution/requestApproval','item/fileChange/requestApproval'}:await self.rpc.reply(obj['id'],{'decision':'decline'})
                    else:await self.rpc.reply(obj['id'],error={'code':-32601,'message':'GoBot denies tool requests'})
                    continue
                for delta in parser.parse(obj):
                    mark("assistant_delta");yield delta
                if parser.completed:return
            raise RuntimeError('App Server disconnected before completion')
        finally:
            if not parser.completed:await self.interrupt()

def codex_exec_argv(executable,prompt,workspace):
    return [executable,'-a','on-request','exec','--json','--sandbox','read-only','--ephemeral','--ignore-user-config','--cd',str(workspace),'--',prompt]

class ProcessRunner:
    """No public executable selection. Tests use a dedicated fixture executable.
    Live CLI admission requires a new reviewed OS/tool containment implementation.
    """
    def __init__(self,argv,workspace,fixture=False):
        if not fixture:raise PermissionError('Live subprocess admission is disabled')
        self.argv=list(argv);self.workspace=workspace;self.process=None;self.stderr='';self.children={}
    async def cleanup(self):
        if not self.process:return
        import psutil
        try:
            for child in psutil.Process(self.process.pid).children(recursive=True):self.children[child.pid]=child
        except psutil.NoSuchProcess:pass
        for child in self.children.values():
            try:child.terminate()
            except psutil.NoSuchProcess:pass
        if self.process.returncode is None:
            try:self.process.terminate()
            except ProcessLookupError:pass
        try:await asyncio.wait_for(self.process.wait(),2)
        except TimeoutError:self.process.kill();await self.process.wait()
        for child in self.children.values():
            try:
                if child.is_running():child.kill()
            except psutil.NoSuchProcess:pass
    async def lines(self,timeout=5):
        # Windows cmd/ps1 shims are intentionally not accepted as executables.
        if Path(self.argv[0]).suffix.lower() in {'.cmd','.bat','.ps1'}:raise PermissionError('Shell shim denied')
        opts={'creationflags':0x08000000} if os.name=='nt' else {'start_new_session':True}
        self.process=await asyncio.create_subprocess_exec(*self.argv,cwd=self.workspace,stdin=asyncio.subprocess.DEVNULL,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,limit=262144,**opts)
        async def drain():
            while chunk:=await self.process.stderr.read(4096):self.stderr=(self.stderr+redact(chunk.decode(errors='replace')))[-4096:]
        stderr_task=asyncio.create_task(drain())
        try:
            async with asyncio.timeout(timeout):
                while line:=await self.process.stdout.readline():
                    import psutil
                    try:
                        for child in psutil.Process(self.process.pid).children(recursive=True):self.children[child.pid]=child
                    except psutil.NoSuchProcess:pass
                    yield json.loads(line)
                code=await self.process.wait()
                if code:raise RuntimeError('CLI exited unsuccessfully')
        finally:
            await self.cleanup()
            try:await asyncio.wait_for(stderr_task,2)
            except TimeoutError:stderr_task.cancel();await asyncio.gather(stderr_task,return_exceptions=True)

class AppServerTransport:
    """Bounded JSON-line wire transport for a pre-admitted stdio process.
    Does not start or admit an executable. Remote HTTP clients cannot select a process.
    """
    def __init__(self,reader,writer,timeout=5):
        self.reader=reader;self.writer=writer;self.timeout=timeout;self.pending={};self.queue=asyncio.Queue(maxsize=32);self.sequence=0;self.pump=None
    async def send(self,obj):
        self.writer.write(json.dumps(obj,ensure_ascii=False).encode()+b'\n');await self.writer.drain()
    async def start(self):
        async def read():
            try:
                while line:=await self.reader.readline():
                    if len(line)>262144:raise ValueError('RPC record limit')
                    obj=json.loads(line)
                    if 'id' in obj and 'method' not in obj and obj['id'] in self.pending:
                        future=self.pending.pop(obj['id'])
                        if 'error' in obj:future.set_exception(AgentError(failure_code(obj['error'])))
                        else:future.set_result(obj.get('result',{}))
                    else:await self.queue.put(obj)
            finally:
                for future in self.pending.values():
                    if not future.done():future.set_exception(RuntimeError('App Server EOF'))
                self.pending.clear()
                if self.queue.full():self.queue.get_nowait()
                self.queue.put_nowait(None)
        self.pump=asyncio.create_task(read())
    async def request(self,method,params):
        self.sequence+=1;ident=self.sequence;future=asyncio.get_running_loop().create_future();self.pending[ident]=future
        await self.send({'id':ident,'method':method,'params':params})
        try:return await asyncio.wait_for(future,self.timeout)
        finally:self.pending.pop(ident,None)
    async def notify(self,method,params):await self.send({'method':method,'params':params})
    async def reply(self,ident,result=None,error=None):await self.send({'id':ident,**({'error':error} if error else {'result':result})})
    async def events(self):
        while (item:=await self.queue.get()) is not None:yield item
    async def close(self):
        if self.pump:self.pump.cancel();await asyncio.gather(self.pump,return_exceptions=True)
        self.writer.close()
