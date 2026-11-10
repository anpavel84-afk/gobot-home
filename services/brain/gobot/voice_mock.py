"""Fixture-only XiaoZhi WS harness. No recognition or synthesized speech."""
import asyncio,json,uuid,hmac
import httpx,websockets
from fastapi import FastAPI,HTTPException,Response,Request
from .protocol import pack_opus,unpack_opus
from .ui import ImageStore
# Valid Opus comfort packet fixture; not a Russian speech synthesizer.
SILENCE=b'\xf8\xff\xfe'
class VoiceMock:
    def __init__(self,settings,device_token,brain_url='http://127.0.0.1:18781'):
        self.settings=settings;self.device_token=device_token;self.brain_url=brain_url
    async def handle(self,ws):
        headers=ws.request.headers
        if headers.get('Device-Id')!='mock-device' or not hmac.compare_digest(headers.get('Authorization',''),'Bearer '+self.device_token):await ws.close(1008,'Unauthorized device');return
        version=int(headers.get('Protocol-Version','1'));session=str(uuid.uuid4());task=None;listening=False;audio_seen=False
        async def send(value):await ws.send(json.dumps(value,ensure_ascii=False))
        async def respond():
            try:
                # ASR fixture is intentionally constant and does not decode microphone speech.
                utterance='Поставь таймер на пять минут'
                await send({'type':'stt','text':utterance,'session_id':session})
                await send({'type':'tts','state':'start','session_id':session})
                async with httpx.AsyncClient(trust_env=False,timeout=10) as client:
                    async with client.stream('POST',self.brain_url+'/api/v1/chat/stream',headers={'Authorization':'Bearer '+self.settings.api_token},json={'text':utterance,'device_id':'mock-device','conversation_id':session,'provider':'mock'}) as response:
                        response.raise_for_status()
                        async for line in response.aiter_lines():
                            if not line.startswith('data: '):continue
                            event=json.loads(line[6:])
                            if event['type']=='sentence_ready':
                                await send({'type':'tts','state':'sentence_start','text':event['data']['text'],'session_id':session})
                                await ws.send(pack_opus(SILENCE,version))
                            elif event['type']=='widget_command':await send(event['data']['command'])
                await send({'type':'tts','state':'stop','session_id':session})
            except asyncio.CancelledError:
                await send({'type':'tts','state':'stop','session_id':session});raise
        try:
            async for message in ws:
                if isinstance(message,bytes):
                    if not listening:await ws.close(1008,'listen required');return
                    unpack_opus(message,version);audio_seen=True;continue
                obj=json.loads(message);kind=obj.get('type')
                if kind=='hello':
                    if obj.get('audio_params',{}).get('format')!='opus' or version not in {1,2,3}:await ws.close(1008,'Unsupported audio');return
                    await send({'type':'hello','version':version,'transport':'websocket','session_id':session,'audio_params':{'format':'opus','sample_rate':24000,'channels':1,'frame_duration':20}})
                elif kind=='listen':
                    if obj.get('state')=='start':listening=True;audio_seen=False
                    elif obj.get('state')=='stop':
                        listening=False
                        if task and not task.done():task.cancel();await asyncio.gather(task,return_exceptions=True)
                        if audio_seen:task=asyncio.create_task(respond())
                elif kind=='abort':
                    if task and not task.done():task.cancel();await asyncio.gather(task,return_exceptions=True)
                    else:await send({'type':'tts','state':'stop','session_id':session})
        finally:
            if task:task.cancel();await asyncio.gather(task,return_exceptions=True)
    async def serve(self,port=18783):
        async def health(connection,request):
            if request.path=='/healthz':return connection.respond(200,'GoBot mock voice fixture\n')
        async with websockets.serve(self.handle,'127.0.0.1',port,max_size=65536,max_queue=8,ping_interval=20,process_request=health):await asyncio.Future()

def image_app(settings=None):
    if settings is None:
        from .config import load
        settings=load()
    app=FastAPI(docs_url=None,redoc_url=None,openapi_url=None);store=ImageStore();app.state.store=store
    @app.get('/healthz')
    async def health():return {'status':'ok','service':'mock-image-origin'}
    @app.post('/api/v1/images')
    async def mint(request:Request):
        if not hmac.compare_digest(request.headers.get('authorization',''),'Bearer '+settings.api_token):raise HTTPException(401,'Authentication required')
        if request.headers.get('content-type')!='image/jpeg':raise HTTPException(415,'JPEG required')
        data=bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data)>65536:raise HTTPException(413,'Image too large')
        try:url=store.add(bytes(data))
        except (ValueError,OSError):raise HTTPException(422,'Baseline 240x240 JPEG required')
        return {'url':url,'expires_in_seconds':30,'mock_device_only':True}
    @app.get('/images/{key}')
    async def image(key:str):
        try:data=store.get(key)
        except KeyError:raise HTTPException(404)
        return Response(data,media_type='image/jpeg',headers={'Content-Length':str(len(data)),'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})
    return app
