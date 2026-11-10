"""Temporary acceptance gateway: pinned client/factory, same Brain and private HTTPS.

No credentials are copied. Existing owner consents remain required. Limits reserve
attempts before forwarding and never refund uncertain requests or retry providers.
"""
import asyncio,hashlib,importlib.util,json,subprocess,time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
REVISION='a71b71e987efdfe01884e34de10712782c0e36ac'
RUN=ROOT/'run/phone-acceptance'

def prepare():
    """Export only public, already-audited tracked code; leave the worktree intact."""
    folder=RUN/REVISION;folder.mkdir(parents=True,exist_ok=True)
    paths=subprocess.run(['git','ls-tree','-r','--name-only',REVISION,'services/phone/dist','services/brain','tests'],cwd=ROOT,check=True,capture_output=True,text=True).stdout.splitlines()
    manifest={}
    for relative in paths:
        target=(folder/relative).resolve()
        if not target.is_relative_to(folder.resolve()):raise ValueError('snapshot_path')
        raw=subprocess.run(['git','show',REVISION+':'+relative],cwd=ROOT,check=True,capture_output=True).stdout
        target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw);manifest[relative]=hashlib.sha256(raw).hexdigest()
    (folder/'manifest.json').write_text(json.dumps({'commit':REVISION,'sha256':manifest},indent=2))
    return folder

class Budget:
    def __init__(self,path):self.path=Path(path);self.lock=asyncio.Lock()
    async def reserve(self,kind,ident,seconds=0):
        async with self.lock:
            data=json.loads(self.path.read_text())
            if data.get('authorization')!='owner-20261110-phone-3stt-2flash-800tts' or time.time()>data['expires']:raise ValueError('acceptance_authorization_expired')
            digest=hashlib.sha256(ident.encode()).hexdigest()
            if digest in data['request_hashes']:raise ValueError('acceptance_duplicate_not_retried')
            if kind=='stt':
                if not 0<seconds<=15 or data['stt_attempts']>=3 or data['stt_seconds']+seconds>45:raise ValueError('acceptance_stt_budget_exhausted')
                data['stt_attempts']+=1;data['stt_seconds']+=seconds
            elif kind=='chat':
                if data['chat_reservations']>=2:raise ValueError('acceptance_flash_budget_exhausted')
                data['chat_reservations']+=1;data['tts_characters_reserved']+=400
            data['request_hashes'].append(digest)
            temp=self.path.with_suffix('.tmp');temp.write_text(json.dumps(data,indent=2));temp.replace(self.path)
            return data

def authorize():
    RUN.mkdir(parents=True,exist_ok=True);path=RUN/'budget.json'
    if path.exists():raise ValueError('Acceptance budget already exists; no automatic reset')
    path.write_text(json.dumps({'authorization':'owner-20261110-phone-3stt-2flash-800tts','created':time.time(),'expires':time.time()+7200,
        'active':True,'stt_attempts':0,'stt_seconds':0,'chat_reservations':0,'tts_characters_reserved':0,'request_hashes':[]},indent=2))

def create_app(settings=None,budget_path=None):
    from starlette.responses import FileResponse,JSONResponse
    from gobot.audio import Speech
    folder=RUN/REVISION
    manifest=json.loads((folder/'manifest.json').read_text())
    for relative,digest in manifest['sha256'].items():
        if hashlib.sha256((folder/relative).read_bytes()).hexdigest()!=digest:raise ValueError('Acceptance snapshot changed')
    # Compile the committed gateway with its original project __file__; all
    # paths for keys, cached clips and internal APIs retain their normal scope.
    source=(folder/'services/brain/gobot/browser.py').read_bytes()
    module=importlib.util.module_from_spec(importlib.util.spec_from_loader('gobot.acceptance_browser',loader=None))
    module.__file__=str(ROOT/'services/brain/gobot/browser.py');module.__package__='gobot'
    exec(compile(source,module.__file__,'exec'),module.__dict__)
    def pinned_file(path,*args,**kwargs):
        candidate=Path(path)
        try:relative=candidate.relative_to(ROOT/'services/phone/dist')
        except ValueError:return FileResponse(path,*args,**kwargs)
        return FileResponse(folder/'services/phone/dist'/relative,*args,**kwargs)
    module.FileResponse=pinned_file
    base_devices=module.DeviceStore
    class AcceptanceDevices(base_devices):
        def profile(self,owner):
            profile=super().profile(owner)
            # This phone budget excludes image generation. Do not mutate the
            # saved preference; mask it only for the acceptance request.
            profile.screen.generation_allowed=False;profile.screen.generation_consent=False
            return profile
    module.DeviceStore=AcceptanceDevices
    app=module.create_browser_app(settings);budget=Budget(budget_path or RUN/'budget.json');decoder=Speech(api_key='')
    @app.get('/api/acceptance/status')
    async def status():
        data=json.loads(budget.path.read_text())
        return {'active':data['active'],'client_commit':REVISION,'expires':data['expires'],'stt_attempts':data['stt_attempts'],
            'stt_seconds':data['stt_seconds'],'chat_reservations':data['chat_reservations'],'tts_characters_reserved':data['tts_characters_reserved'],
            'limits':{'stt_attempts':3,'stt_seconds':45,'flash_requests':2,'tts_characters':800},'contains_content':False}
    @app.middleware('http')
    async def limits(request,call_next):
        # Leave the original gateway ACL and origin checks in force.
        if request.client.host not in module.PEERS or request.headers.get('host')!=module.HOST+':'+str(module.PORT) or request.headers.get('origin')!=module.ORIGIN:return await call_next(request)
        path=request.url.path
        if not json.loads(budget.path.read_text()).get('active'):return await call_next(request)
        if request.method!='POST' or path not in {'/api/chat/stream','/api/audio/transcribe'}:return await call_next(request)
        raw=bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw)>(20000 if path=='/api/chat/stream' else 8*1024*1024):return JSONResponse({'detail':'acceptance_body_limit'},413)
        try:
            if path=='/api/audio/transcribe':
                if request.query_params.get('provider')!='openai' or request.query_params.get('paid_consent')!='true':raise ValueError('acceptance_requires_explicit_openai_stt')
                pcm=await decoder.decode(bytes(raw),request.headers.get('content-type','').split(';')[0]);seconds=len(pcm)/32000
                await budget.reserve('stt',request.query_params.get('trace_id',''),seconds)
                del pcm
            else:
                from gobot.conversation_control import closing_intent
                body=json.loads(raw)
                if body.get('usage_consent') is not True:raise ValueError('quota_consent_required')
                closing=closing_intent(body.get('text',''))=='end_conversation'
                if not closing:await budget.reserve('chat',body.get('request_id') or body['turn_id'])
                body.update(mode='fast',model_id='gemini-3.8-flash-low',remember=False,expensive_fallback_approved=False,context_detail='standard',tts_provider='openai',tts_character_limit=0 if closing else 400)
                if closing:body['speak']=False
                raw=bytearray(json.dumps(body).encode())
        except Exception as error:
            code=str(error) if isinstance(error,ValueError) else 'acceptance_validation_failed'
            if not code.startswith(('acceptance_','quota_')):code='acceptance_invalid_request'
            return JSONResponse({'detail':code},429)
        request._body=bytes(raw)
        return await call_next(request)
    class FileSTTOnly:
        async def __call__(self,scope,receive,send):
            if scope['type']=='websocket' and scope.get('path')=='/api/audio/live' and json.loads(budget.path.read_text()).get('active'):
                await send({'type':'websocket.close','code':1008});return
            await app(scope,receive,send)
    return FileSTTOnly()

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--authorize',action='store_true');parser.add_argument('--finish',action='store_true');args=parser.parse_args()
    if args.finish:
        path=RUN/'budget.json';value=json.loads(path.read_text());value['active']=False;value['finished']=time.time();path.write_text(json.dumps(value,indent=2));print('Acceptance budget closed; pinned normal client retained');raise SystemExit(0)
    prepare()
    if args.authorize:authorize()
    print('Pinned acceptance snapshot prepared; no model/STT/TTS calls made')
