"""OpenAI STT transports. Completed-file and live-input streaming are distinct."""
import asyncio,base64,io,json,time,wave
from contextlib import suppress
import httpx
from .processes import AgentError
from .secrets_store import load_openai_key
from .telemetry import mark

FILE_MODEL='gpt-transcribe'
LIVE_MODEL='gpt-live-transcribe'

class OpenAIRecognition:
    def __init__(self,api_key=None,transport=None,connector=None):
        self.api_key=api_key;self.transport=transport;self.connector=connector
    async def key(self,consent):
        if not consent:raise AgentError('openai_stt_consent_required')
        key=self.api_key if self.api_key is not None else await asyncio.to_thread(load_openai_key)
        if not key:raise AgentError('openai_stt_key_missing')
        return key
    async def file(self,data,mime,*,paid_consent=False):
        key=await self.key(paid_consent)
        ext={'audio/wav':'wav','audio/x-wav':'wav','audio/wave':'wav','audio/webm':'webm','audio/mp4':'mp4','audio/ogg':'ogg'}.get(mime.split(';')[0])
        if not ext or not 100<=len(data)<=8*1024*1024:raise AgentError('invalid_audio_upload')
        start=time.perf_counter()
        try:
            async with httpx.AsyncClient(transport=self.transport,trust_env=False,timeout=httpx.Timeout(45,connect=5)) as client:
                mark('stt_provider_submit')
                response=await client.post('https://api.openai.com/v1/audio/transcriptions',headers={'Authorization':'Bearer '+key},
                    files={'file':('utterance.'+ext,data,mime.split(';')[0])},
                    data={'model':FILE_MODEL,'languages[]':'ru','response_format':'json'})
                if response.status_code!=200:
                    code={401:'openai_stt_auth_failed',403:'openai_stt_access_denied',404:'openai_stt_model_unavailable',429:'openai_stt_rate_or_balance_limited'}.get(response.status_code,'openai_stt_unavailable')
                    raise AgentError(code)
                mark('stt_provider_response')
                obj=response.json()
                if not isinstance(obj.get('text'),str) or len(obj['text'])>8000:raise AgentError('invalid_transcript')
                return {'text':obj['text'],'provider':'openai','model':FILE_MODEL,'final':True,
                        'stt_ms':(time.perf_counter()-start)*1000,'first_interim_ms':None,'automatic_fallback':False}
        except (AgentError,asyncio.CancelledError):raise
        except Exception:raise AgentError('openai_stt_unavailable') from None

    async def live(self,chunks,*,paid_consent=False):
        """chunks: async iterator of 24kHz mono PCM16. EOF commits one stable turn.
        Deltas are UI-only; the caller must never dispatch LLM before stt_final.
        """
        key=await self.key(paid_consent)
        from websockets.asyncio.client import connect
        connector=self.connector or connect
        started=time.perf_counter();first=None;committed=None;count=0
        try:
            mark('stt_live_handshake_start')
            async with asyncio.timeout(100):
                async with connector('wss://api.openai.com/v1/realtime?intent=transcription',
                    additional_headers={'Authorization':'Bearer '+key},proxy=None,open_timeout=5,close_timeout=2,max_size=1048576,max_queue=4) as ws:
                    await ws.send(json.dumps({'type':'session.update','session':{'type':'transcription','audio':{'input':{
                        'format':{'type':'audio/pcm','rate':24000},'transcription':{'model':LIVE_MODEL,'languages':['ru'],'delay':'low'},'turn_detection':None}}}}))
                    while True:
                        item=json.loads(await ws.recv())
                        if item.get('type')=='error':raise AgentError('openai_live_stt_configuration_rejected')
                        if item.get('type')=='session.updated':break
                    mark('stt_live_handshake_end')
                    yield {'type':'stt_ready','data':{'provider':'openai','model':LIVE_MODEL}}
                    async def send_audio():
                        nonlocal count,committed
                        async for chunk in chunks:
                            if len(chunk)%2 or len(chunk)>48000:raise AgentError('invalid_pcm_chunk')
                            count+=len(chunk)
                            if count>24000*2*60:raise AgentError('audio_too_large')
                            await ws.send(json.dumps({'type':'input_audio_buffer.append','audio':base64.b64encode(chunk).decode()}))
                        if count<4800:raise AgentError('audio_too_short')
                        mark('stt_live_commit');committed=time.perf_counter()
                        await ws.send(json.dumps({'type':'input_audio_buffer.commit'}))
                    sender=asyncio.create_task(send_audio())
                    receive=None
                    try:
                        while True:
                            receive=asyncio.create_task(ws.recv())
                            done,_=await asyncio.wait({receive,sender},return_when=asyncio.FIRST_COMPLETED)
                            if sender in done and sender.exception():
                                receive.cancel();await asyncio.gather(receive,return_exceptions=True);raise sender.exception()
                            raw=await receive
                            item=json.loads(raw);kind=item.get('type')
                            if kind=='error':raise AgentError('openai_live_stt_unavailable')
                            if kind=='conversation.item.input_audio_transcription.delta':
                                if first is None:first=(time.perf_counter()-started)*1000;mark('stt_partial')
                                yield {'type':'stt_partial','data':{'text':item.get('delta',''),'item_id':item.get('item_id'),'stable':False,'first_interim_ms':first}}
                            if kind=='conversation.item.input_audio_transcription.completed':
                                if committed is None:continue
                                yield {'type':'stt_final','data':{'text':item.get('transcript',''),'item_id':item.get('item_id'),'stable':True,
                                    'first_interim_ms':first,'final_ms':(time.perf_counter()-started)*1000,
                                    'speech_end_to_final_ms':(time.perf_counter()-committed)*1000,'provider':'openai','model':LIVE_MODEL}}
                                return
                            if kind=='conversation.item.input_audio_transcription.failed':raise AgentError('openai_live_stt_failed')
                    finally:
                        if receive and not receive.done():receive.cancel();await asyncio.gather(receive,return_exceptions=True)
                        sender.cancel();await asyncio.gather(sender,return_exceptions=True)
        except (AgentError,asyncio.CancelledError,GeneratorExit):raise
        except Exception:raise AgentError('openai_live_stt_unavailable') from None
