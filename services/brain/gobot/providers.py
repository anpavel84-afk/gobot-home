import asyncio,json
import httpx
from .security import canonical,signed_request,verify_event

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
    messages=[{'role':'system','content':'Отвечай по-русски кратко. Инструменты недоступны. Разрешённый summary: '+context['summary']+'\nФакты: '+json.dumps(context['facts'],ensure_ascii=False)}]+[{'role':m['role'],'content':m['content']} for m in context['messages']]
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
    body=canonical({'text':req.text,'provider':req.provider,'context':context,'turn_id':req.turn_id})
    headers=signed_request(settings.bridge_secret,body);seq=0
    async with httpx.AsyncClient(timeout=httpx.Timeout(settings.timeout,connect=2),trust_env=False) as client:
        async with client.stream('POST',settings.bridge_url+'/v1/stream',content=body,headers={**headers,'Content-Type':'application/json'}) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line:continue
                item=verify_event(settings.bridge_secret,headers['X-GoBot-Nonce'],seq,json.loads(line));seq+=1
                if item['type']=='text_delta':yield item['text']
                elif item['type']=='error':raise RuntimeError('Agent unavailable')
                elif item['type']=='final':return

class SentenceBuffer:
    def __init__(self):self.buffer=''
    def feed(self,delta,final=False):
        import re
        self.buffer+=delta;out=[]
        while True:
            match=re.search(r'[.!?…](?:["»])?(?:\s|$)',self.buffer)
            if not match:break
            end=match.end();out.append(self.buffer[:end].strip());self.buffer=self.buffer[end:]
        if final and self.buffer.strip():out.append(self.buffer.strip());self.buffer=''
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
