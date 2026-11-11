import asyncio,json,sys,os
from pathlib import Path
import pytest
from gobot.agents import CursorAdapter,GeminiCLIAdapter,CodexEventAdapter,CodexAppServerAdapter,NDJSON,ProcessRunner,codex_exec_argv
from gobot.security import redact

def test_ndjson_partial_utf8_and_incomplete():
    data='{"type":"message","content":"Привет"}\n'.encode();p=NDJSON();out=[]
    for byte in data:out+=p.feed(bytes([byte]))
    assert out[0]['content']=='Привет' and not p.buffer
    assert p.feed(b'{"text":')==[]
    with pytest.raises(json.JSONDecodeError):p.feed(b'',final=True)

def test_cursor_official_partial_flush_rules_no_duplicate():
    p=CursorAdapter();out=[]
    def msg(text,**fields):return {'type':'assistant','message':{'role':'assistant','content':[{'type':'text','text':text}]},**fields}
    for obj in [msg('При',timestamp_ms=1),msg('вет',timestamp_ms=2),msg('Привет',timestamp_ms=3,model_call_id='duplicate'),msg('Привет'),{'type':'tool_call','result':'SECRET'},{'type':'thinking','text':'REASONING'},{'type':'result','subtype':'success','result':'Привет','is_error':False}]:out+=p.parse(obj)
    assert ''.join(out)=='Привет' and p.completed
    assert p.parse({'type':'result','subtype':'success','result':'Привет'})==[]

def test_cursor_complete_mode():
    p=CursorAdapter(partial=False)
    assert p.parse({'type':'assistant','message':{'role':'assistant','content':[{'type':'text','text':'Ответ'}]}})==['Ответ']
    assert p.parse({'type':'result','subtype':'success','result':'Ответ'})==[]

def test_gemini_only_assistant_and_final():
    p=GeminiCLIAdapter();out=[]
    for kind in ['tool_use','tool_result','init','error','usage','debug']:out+=p.parse({'type':kind,'content':'PRIVATE'})
    out+=p.parse({'type':'message','role':'user','content':'INPUT'})
    for d in ['При','вет']:out+=p.parse({'type':'message','role':'assistant','delta':True,'content':d})
    out+=p.parse({'type':'result','status':'success','usage':{'secret':'PRIVATE'}})
    assert ''.join(out)=='Привет'

def test_codex_no_reasoning_stdout_and_duplicates():
    p=CodexEventAdapter();out=[]
    for t in ['reasoning','command_execution','mcp_tool_call']:out+=p.parse({'type':'item.completed','item':{'type':t,'text':'PRIVATE'}})
    item={'type':'item.completed','item':{'type':'agent_message','id':'a','text':'Ответ'}}
    out+=p.parse(item);out+=p.parse(item);out+=p.parse({'type':'turn.completed'})
    assert out==['Ответ'] and p.completed
    assert CodexEventAdapter().parse({'method':'item/agentMessage/delta','params':{'delta':'Привет'}})==['Привет']

class FixtureRPC:
    def __init__(self):self.calls=[];self.replies=[]
    async def request(self,method,params):
        self.calls.append((method,params))
        if method.startswith('thread/'):return {'thread':{'id':'thread1'}}
        if method=='turn/start':return {'turn':{'id':'turn1'}}
        return {}
    async def notify(self,method,params):self.calls.append((method,params))
    async def reply(self,id,result=None,error=None):self.replies.append((id,result,error))
    async def events(self):
        yield {'id':4,'method':'item/commandExecution/requestApproval','params':{'command':'whoami'}}
        yield {'id':5,'method':'item/tool/call','params':{'text':'PRIVATE'}}
        yield {'method':'item/reasoning/textDelta','params':{'delta':'PRIVATE'}}
        yield {'method':'item/agentMessage/delta','params':{'delta':'Ответ'}}
        yield {'method':'turn/completed','params':{'turn':{'status':'completed'}}}

def test_codex_lifecycle_and_denied_approvals(tmp_path):
    async def exercise():
        rpc=FixtureRPC();a=CodexAppServerAdapter(rpc,tmp_path)
        await a.initialize();await a.thread();out=[d async for d in a.stream('Вопрос')]
        await a.thread(resume='thread1');await a.interrupt()
        assert out==['Ответ']
        assert [m for m,_ in rpc.calls]==['initialize','initialized','thread/start','turn/start','thread/resume','turn/interrupt']
        assert rpc.calls[2][1]['sandbox']=='read-only'
        assert rpc.replies[0][1]=={'decision':'decline'} and rpc.replies[1][2]['code']==-32601
    asyncio.run(exercise())

def test_live_process_denied_and_safe_argv(tmp_path):
    with pytest.raises(PermissionError):ProcessRunner(['codex','x'],tmp_path)
    assert '--mode' in CursorAdapter.argv('cursor','$(bad)',tmp_path)
    assert '--sandbox' in codex_exec_argv('codex','& bad',tmp_path)
    assert GeminiCLIAdapter.argv('gemini','; bad')[-3:]==['; bad','--output-format','stream-json']

@pytest.mark.parametrize('mode',['timeout','cancel','exit'])
def test_child_cleanup_stderr_and_exit(tmp_path,mode):
    fixture=tmp_path/'fixture.py';child_pid=tmp_path/'child.pid'
    fixture.write_text("import subprocess,sys,time,pathlib\nchild=subprocess.Popen([sys.executable,'-c','import time; time.sleep(20)'])\npathlib.Path(sys.argv[1]).write_text(str(child.pid))\nprint('Bearer hidden-value',file=sys.stderr,flush=True)\nprint('{\"type\":\"init\"}',flush=True)\ntime.sleep(0.1 if sys.argv[2]=='exit' else 20)\nsys.exit(3)\n")
    async def exercise():
        runner=ProcessRunner([sys.executable,str(fixture),str(child_pid),mode],tmp_path,fixture=True)
        iterator=runner.lines(timeout=.7)
        assert (await anext(iterator))['type']=='init'
        if mode=='cancel':await iterator.aclose()
        else:
            with pytest.raises((TimeoutError,RuntimeError)):
                async for item in iterator:pass
        assert runner.process.returncode is not None
        assert 'hidden-value' not in runner.stderr
        import psutil
        pid=int(child_pid.read_text())
        try:
            p=psutil.Process(pid)
            p.wait(timeout=2)
        except psutil.NoSuchProcess:
            pass  # The cleaned-up child may disappear between observation and wait.
        except psutil.TimeoutExpired:
            raise AssertionError('Fixture child survived cleanup')
    asyncio.run(exercise())

def test_redaction():
    assert 'abcdef12345' not in redact('api_key=abcdef12345 Bearer abcdef12345 sk-abcdef12345')
