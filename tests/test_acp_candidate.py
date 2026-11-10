"""Actual stdio RPC with an in-memory agent; no native/model prompt calls."""
import asyncio,json
from contextlib import asynccontextmanager
from types import SimpleNamespace
import pytest
from gobot.antigravity_acp import AcpRuntime,AntigravityACPAdapter,admitted
from gobot.processes import AgentError

class NativeFixture:
    def __init__(self,scenario='normal'):
        self.scenario=scenario;self.calls=[];self.spawns=0;self.closed=0;self.serial=0
    @asynccontextmanager
    async def process(self,*args,**kwargs):
        self.spawns+=1;fixture=self;reader=asyncio.StreamReader()
        def feed(item):reader.feed_data(json.dumps({'jsonrpc':'2.0',**item}).encode()+b'\n')
        class Writer:
            def write(self,raw):
                request=json.loads(raw);fixture.calls.append(request)
                assert request['jsonrpc']=='2.0'
                method=request.get('method');ident=request.get('id');params=request.get('params',{})
                if not method:return
                if method=='initialize':
                    assert params['clientCapabilities']['terminal'] is False
                    feed({'id':ident,'result':{'protocolVersion':1,'agentCapabilities':{'sessionCapabilities':{'close':{}}}}})
                elif method=='session/new':
                    assert params['mcpServers']==[]
                    fixture.serial+=1;feed({'id':ident,'result':{'sessionId':'session-'+str(fixture.serial),'models':{'currentModelId':'gemini-3.8-flash-low'}}})
                elif method=='session/prompt':
                    session=params['sessionId']
                    if fixture.scenario=='eof':reader.feed_eof();return
                    if fixture.scenario=='malformed':reader.feed_data(b'{invalid\n');return
                    if fixture.scenario=='permission':
                        feed({'id':'deny-test','method':'session/request_permission','params':{'sessionId':session,'options':[{'kind':'allow_always','optionId':'danger'}]}})
                    elif fixture.scenario=='filesystem':
                        feed({'id':'deny-test','method':'fs/read_text_file','params':{'sessionId':session,'path':'NEVER_READ'}})
                    elif fixture.scenario=='tool':
                        feed({'method':'session/update','params':{'sessionId':session,'update':{'sessionUpdate':'tool_call','toolCallId':'bad'}}})
                    else:
                        feed({'method':'session/update','params':{'sessionId':session,'update':{'sessionUpdate':'agent_message_chunk','content':{'type':'text','text':'Fixture answer.'}}}})
                    if fixture.scenario!='cancel':feed({'id':ident,'result':{'stopReason':'end_turn'}})
                elif method=='session/close':feed({'id':ident,'result':{}})
            async def drain(self):pass
            def close(self):
                if not reader.at_eof():reader.feed_eof()
        try:yield SimpleNamespace(stdout=reader,stdin=Writer())
        finally:self.closed+=1

def test_pool_reuses_process_but_never_session_or_prompt_history():
    async def run():
        fixture=NativeFixture();runtime=AcpRuntime(fixture.process)
        for owner in ['one','two']:
            context={}
            assert [x async for x in runtime.stream('Only '+owner,context,'gemini-3.8-flash-low')]==['Fixture answer.']
            assert context['_provider_session_id'].startswith('session-')
        assert fixture.spawns==1
        prompts=[r for r in fixture.calls if r.get('method')=='session/prompt']
        assert prompts[0]['params']['sessionId']!=prompts[1]['params']['sessionId']
        assert 'one' not in prompts[1]['params']['prompt'][0]['text']
        assert not any(r.get('method') in {'session/load','session/resume'} for r in fixture.calls)
        await runtime.close();assert fixture.closed==1
    asyncio.run(run())

@pytest.mark.parametrize('scenario',['permission','filesystem','tool','eof','malformed'])
def test_native_tool_requests_and_process_failures_abort_without_retry(scenario):
    async def run():
        fixture=NativeFixture(scenario);runtime=AcpRuntime(fixture.process)
        with pytest.raises((AgentError,RuntimeError)):
            _=[x async for x in runtime.stream('fixture',{},'gemini-3.8-flash-low')]
        assert fixture.spawns==1 and fixture.closed==1
        if scenario=='permission':
            reply=next(r for r in fixture.calls if r.get('id')=='deny-test' and not r.get('method'))
            assert reply['result']['outcome']['outcome']=='cancelled'
    asyncio.run(run())

def test_cancellation_closes_runtime_and_bounded_queue_does_not_spawn():
    async def run():
        fixture=NativeFixture('cancel');runtime=AcpRuntime(fixture.process)
        stream=runtime.stream('fixture',{},'gemini-3.8-flash-low')
        assert await anext(stream)=='Fixture answer.'
        with pytest.raises(AgentError,match='acp_queue_busy'):
            _=[x async for x in runtime.stream('parallel',{},'gemini-3.8-flash-low')]
        await stream.aclose()
        assert any(r.get('method')=='session/cancel' for r in fixture.calls)
        assert fixture.closed==1
    asyncio.run(run())

def test_candidate_is_denied_before_prompt_and_defaults_are_unchanged(monkeypatch):
    from gobot import antigravity_acp as acp
    from gobot.routing import RouterPolicy
    assert RouterPolicy().antigravity_transport=='stream_json'
    monkeypatch.setattr(acp,'admitted',lambda:False)
    async def run():
        with pytest.raises(AgentError,match='acp_isolation_not_verified'):
            _=[x async for x in AntigravityACPAdapter().stream('never sent',{})]
    asyncio.run(run())
