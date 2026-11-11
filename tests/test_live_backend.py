"""Luna fixtures: exact count gate, model identity, no tools, quotas and cancellation."""
import asyncio,json,time
import httpx,pytest
from gobot.live_backend import LiveBackend,MODEL
from gobot.owner_testing import OwnerTesting,OwnerTestPolicy

def configured(tmp_path,handler):
    owner=OwnerTesting(tmp_path/'owner')
    owner.policy_path.write_text(OwnerTestPolicy(enabled=True,authorization='synthetic',allowed_client_id='owner',live_backend_enabled=True,
        developer_acceptance_expires_at=time.time()+60,developer_live_backend_limit=4).model_dump_json())
    return LiveBackend(tmp_path/'live',owner,key_loader=lambda:'synthetic-key',transport=httpx.MockTransport(handler)),owner

def wire(*,model=MODEL,text='Число 3.14. Это оценка.'):
    events=[{'type':'response.created','response':{'model':model}}]
    events.extend({'type':'response.output_text.delta','delta':delta} for delta in ['Число 3.','14. ','Это оценка.'])
    events.append({'type':'response.completed','response':{'model':model,'status':'completed','usage':{'input_tokens':300,'output_tokens':80,'total_tokens':380,'input_tokens_details':{'cached_tokens':100}}}})
    return '\n\n'.join('data: '+json.dumps(e) for e in events)+'\n\n'

def test_exact_count_limits_model_usage_sentences_and_idempotency(tmp_path):
    async def run():
        requests=[]
        async def handler(request):
            requests.append(request);body=json.loads(request.content)
            assert body['model']==MODEL and body['tools']==[] and body['tool_choice']=='none' and body['reasoning']=={'effort':'none'}
            if request.url.path.endswith('input_tokens'):return httpx.Response(200,json={'object':'response.input_tokens','input_tokens':300})
            assert body['store'] is False and body['max_output_tokens']==512 and body['stream']
            return httpx.Response(200,text=wire(),headers={'content-type':'text/event-stream'})
        backend,owner=configured(tmp_path,handler);spoken=[]
        async def deliver(text):spoken.append(text)
        result=await backend.answer('Синтетический вопрос',{},binding='owner',operation='one',developer=True,on_text=deliver)
        assert spoken==['Число 3.14.','Это оценка.'] and result['input_count']==300
        assert result['estimated_usd']==pytest.approx(.000061)
        with pytest.raises(ValueError,match='already_attempted'):await backend.answer('Другой текст',{},binding='owner',operation='one',developer=True)
        assert len(requests)==2 and owner.status('owner')['attempts_today']['live_backend']==1
        assert 'Синтетический'.encode() not in backend.path.read_bytes()
    asyncio.run(run())

def test_over_budget_input_never_starts_generation(tmp_path):
    async def run():
        requests=[]
        async def handler(request):requests.append(request);return httpx.Response(200,json={'input_tokens':2049})
        backend,owner=configured(tmp_path,handler)
        with pytest.raises(ValueError,match='input_limit'):await backend.answer('Синтетический вопрос',{},binding='owner',operation='one',developer=True)
        assert len(requests)==1 and requests[0].url.path.endswith('input_tokens')
        assert not owner.status('owner')['attempts_today']
    asyncio.run(run())

def test_wrong_model_and_revocation_do_not_leak_output_or_retry(tmp_path):
    async def run():
        requests=[];spoken=[]
        async def handler(request):
            requests.append(request)
            if request.url.path.endswith('input_tokens'):return httpx.Response(200,json={'input_tokens':100})
            return httpx.Response(200,text=wire(model='unrequested-model'))
        backend,owner=configured(tmp_path,handler)
        async def deliver(text):spoken.append(text)
        with pytest.raises(RuntimeError,match='model_mismatch'):await backend.answer('Вопрос',{},binding='owner',operation='one',developer=True,on_text=deliver)
        assert not spoken and len(requests)==2 and owner.status('owner')['pending_usage']==1
        with pytest.raises(asyncio.CancelledError):await backend.answer('Вопрос',{},binding='owner',operation='two',developer=True,is_current=lambda:False)
        assert len(requests)==2
    asyncio.run(run())

def test_two_backend_instances_share_one_active_generation_lease(tmp_path):
    async def run():
        entered=asyncio.Event();release=asyncio.Event();requests=[]
        async def handler(request):
            requests.append(request)
            if request.url.path.endswith('input_tokens'):
                entered.set();await release.wait();return httpx.Response(200,json={'input_tokens':100})
            return httpx.Response(200,text=wire())
        first,owner=configured(tmp_path,handler)
        second=LiveBackend(tmp_path/'live',owner,key_loader=lambda:'synthetic-key',transport=httpx.MockTransport(handler))
        work=asyncio.create_task(first.answer('Первый',{},binding='owner',operation='one',developer=True))
        await entered.wait()
        with pytest.raises(PermissionError,match='busy'):await second.answer('Второй',{},binding='owner',operation='two',developer=True)
        assert len(requests)==1
        release.set();await work
        assert len(requests)==2
    asyncio.run(run())
