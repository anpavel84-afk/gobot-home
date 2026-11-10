import asyncio,json
import httpx
from .security import canonical,signed_request,verify_event
from .processes import AgentError
from .telemetry import mark,CURRENT

class MockAgentAdapter:
    async def stream(self,text,context):
        reply="Это mock-ответ GoBot на русском. Контекст разговора сохранён."
        if 'таймер' in text.lower():reply="Таймер на пять минут подготовлен. Команда показана в mock-интерфейсе."
        for word in reply.split(' '):
            await asyncio.sleep(0.002);yield word+' '

async def fast_stream(settings,req,context):
    if req.provider=='mock' or settings.fast_provider!='openai' or not settings.api_key:
        async for delta in MockAgentAdapter().stream(req.text,context):yield delta
        return
    if not settings.allow_paid:raise PermissionError('Paid integration is disabled')
    if not settings.api_model:raise ValueError('Missing API model')
    from .context_manager import RUNTIME
    messages=[{'role':'system','content':RUNTIME+'\nРазрешённый summary: '+context['summary']+'\nФакты: '+json.dumps(context['facts'],ensure_ascii=False)}]+[{'role':m['role'],'content':m['content']} for m in context['messages']]+[{'role':'user','content':req.text}]
    async with httpx.AsyncClient(timeout=httpx.Timeout(15,connect=3),trust_env=False) as client:
        async with client.stream('POST',settings.api_base.rstrip('/')+'/chat/completions',headers={'Authorization':'Bearer '+settings.api_key},json={'model':settings.api_model,'messages':messages,'stream':True,'max_tokens':700}) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith('data:'):continue
                value=line[5:].strip()
                if value=='[DONE]':break
                obj=json.loads(value)
                delta=(obj.get('choices') or [{}])[0].get('delta',{}).get('content')
                if isinstance(delta,str):yield delta

async def bridge_stream(settings,req,context):
    body=canonical({'text':req.text,'provider':req.provider,'context':context,'turn_id':req.turn_id,'usage_consent':req.usage_consent,'model_id':req.model_id,'trace_id':req.trace_id or req.utterance_id or req.turn_id})
    headers=signed_request(settings.bridge_secret,body);seq=0
    async with httpx.AsyncClient(timeout=httpx.Timeout(settings.timeout,connect=2),trust_env=False) as client:
        async with client.stream('POST',settings.bridge_url+'/v1/stream',content=body,headers={**headers,'Content-Type':'application/json'}) as response:
            if response.status_code==403:raise AgentError('agent_policy_or_consent_required')
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line:continue
                item=verify_event(settings.bridge_secret,headers['X-GoBot-Nonce'],seq,json.loads(line));seq+=1
                if item['type']=='telemetry':context['_bridge_telemetry']=item['trace']
                elif item['type']=='text_delta':mark('bridge_first_text');yield item['text']
                elif item['type']=='usage':context['_provider_usage']=item['usage']
                elif item['type']=='session':context['_provider_session_id']=item['session_id']
                elif item['type']=='error':raise AgentError(item.get('code','agent_unavailable'))
                elif item['type']=='final':return

class SentenceBuffer:
    def __init__(self):self.buffer=''
    def feed(self,delta,final=False):
        import re
        self.buffer+=delta;out=[]
        while True:
            match=None;depth=0
            for candidate in re.finditer(r'[.!?…](?:["»])?(?:\s|$)',self.buffer):
                prefix=self.buffer[:candidate.start()]
                depth=prefix.count('(')-prefix.count(')')
                if depth>0 or prefix.count('```')%2:continue
                if re.search(r'\b(?:г|руб|им|т|д|ул|рис|стр)$',prefix,re.I) and not final:continue
                match=candidate;break
            if not match:break
            end=match.end();out.append(self.buffer[:end].strip());self.buffer=self.buffer[end:]
        if final and self.buffer.strip():out.append(self.buffer.strip());self.buffer=''
        if out:mark("chunker_sentence_ready")
        return [s for s in out if s]

async def cancellable(source,flag):
    iterator=source.__aiter__();pending=None;stop=asyncio.create_task(flag.wait())
    try:
        while True:
            pending=asyncio.create_task(anext(iterator))
            done,_=await asyncio.wait({pending,stop},return_when=asyncio.FIRST_COMPLETED)
            if stop in done:raise asyncio.CancelledError()
            try:yield pending.result()
            except StopAsyncIteration:return
    finally:
        if pending and not pending.done():pending.cancel()
        if pending:await asyncio.gather(pending,return_exceptions=True)
        stop.cancel();await asyncio.gather(stop,return_exceptions=True)
        await iterator.aclose()

async def merge_presentation(source,visual,flag):
    """One text lookahead, one visual task; neither can starve the other."""
    iterator=source.__aiter__();pending=None;stop=asyncio.create_task(flag.wait());text_done=False
    try:
        while not text_done or visual is not None:
            if not text_done and pending is None:pending=asyncio.create_task(anext(iterator))
            waiting={stop}
            if pending is not None:waiting.add(pending)
            if visual is not None:waiting.add(visual)
            done,_=await asyncio.wait(waiting,return_when=asyncio.FIRST_COMPLETED)
            if stop in done:raise asyncio.CancelledError()
            if visual is not None and visual in done:
                try:result=visual.result()
                except Exception:visual=None;yield 'visual_failed',None
                else:visual=None;yield 'visual',result
            if pending is not None and pending in done:
                try:value=pending.result()
                except StopAsyncIteration:
                    text_done=True;pending=None
                    # Flush an unpunctuated answer to speech before waiting for optional art.
                    yield 'text_done',None
                else:
                    pending=None;yield 'text',value
    finally:
        for task in (pending,visual,stop):
            if task is not None:task.cancel()
        await asyncio.gather(*(task for task in (pending,visual,stop) if task is not None),return_exceptions=True)
        await iterator.aclose()
