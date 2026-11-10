import asyncio,io,json,time,types,ast,sys
from pathlib import Path
import pytest
from PIL import Image
from fastapi.testclient import TestClient
from gobot.bridge import create_app
from gobot.security import canonical,signed_request,verify_event
from gobot.ui import UICommand,MockUIRenderer,ImageStore
from gobot.protocol import pack_opus,unpack_opus
from gobot.integrations import PermissionLayer
ROOT=Path(__file__).resolve().parents[1]

def test_bridge_mutual_auth_replay_and_real_denial(settings):
    with TestClient(create_app(settings)) as client:
        body=canonical({'text':'Привет','provider':'mock','context':{},'turn_id':'test'})
        assert client.post('/v1/stream',content=body).status_code==401
        headers=signed_request(settings.bridge_secret,body)
        response=client.post('/v1/stream',content=body,headers=headers);assert response.status_code==200
        rows=[json.loads(line) for line in response.text.splitlines()]
        out=[verify_event(settings.bridge_secret,headers['X-GoBot-Nonce'],i,item) for i,item in enumerate(rows)]
        assert out[-1]['type']=='final' and any(x['type']=='text_delta' for x in out)
        assert client.post('/v1/stream',content=body,headers=headers).status_code==401
        rows[0]['payload']['text']='tamper'
        with pytest.raises(ValueError):verify_event(settings.bridge_secret,headers['X-GoBot-Nonce'],0,rows[0])
        real=canonical({'text':'x','provider':'codex','context':{},'turn_id':'real'})
        assert client.post('/v1/stream',content=real,headers=signed_request(settings.bridge_secret,real)).status_code==403
        assert client.post('/unlisted',content=body).status_code==404

@pytest.mark.parametrize('version',[1,2,3])
def test_opus_framing(version):
    payload=b'\xf8\xff\xfe';frame=pack_opus(payload,version,timestamp=120)
    assert unpack_opus(frame,version)==payload
    if version>1:
        with pytest.raises(ValueError):unpack_opus(frame[:-1],version)
    with pytest.raises(ValueError):pack_opus(b'\xff\xd8BAD',version)

@pytest.mark.parametrize('frame,version',[(b'',1),(b'abc',2),(b'abc',3),(b'abc',4)])
def test_invalid_audio(frame,version):
    with pytest.raises(ValueError):unpack_opus(frame,version)

def test_ui_queue_timer_and_validation():
    renderer=MockUIRenderer();command={'type':'custom','payload':{'namespace':'gobot.ui','version':1,'command':'timer.start','duration_ms':300000}}
    renderer.enqueue(command);assert not renderer.state
    assert renderer.gui_tick()['timer.start']['duration_ms']==300000
    with pytest.raises(ValueError):UICommand(command='timer.start')
    with pytest.raises(ValueError):UICommand(command='shell.exec',text='bad')
    with pytest.raises(ValueError):UICommand(command='status.show',text='x',version=2)

def jpeg(progressive=False,size=(240,240)):
    data=io.BytesIO();Image.new('RGB',size,'navy').save(data,format='JPEG',progressive=progressive);return data.getvalue()
def test_image_policy_mcp_permission_and_ssrf(monkeypatch):
    store=ImageStore();url=store.add(jpeg());key=url.rsplit('/',1)[1]
    assert len(store.get(key))<65536
    for permission,caps in [(False,{'self.screen.preview_image'}),(True,set())]:
        with pytest.raises(PermissionError):store.mcp_call(url,caps,permission)
    call=store.mcp_call(url,{'self.screen.preview_image'},True)
    assert call['type']=='mcp' and call['payload']['params']['name']=='self.screen.preview_image'
    for evil in ['http://169.254.169.254/latest','http://127.0.0.1:18784/images/../x',url+'?url=http://evil']:
        with pytest.raises((ValueError,KeyError)):store.mcp_call(evil,{'self.screen.preview_image'},True)
    for data in [jpeg(True),jpeg(size=(100,100)),b'x'*65537]:
        with pytest.raises(ValueError):store.add(data)
    with pytest.raises(ValueError):store.add(jpeg(),mime='image/png')
    monkeypatch.setattr('gobot.ui.time.time',lambda:time.monotonic()+10**12)
    with pytest.raises(KeyError):store.get(key)

def test_dangerous_home_actions_denied():
    gate=PermissionLayer();assert gate.authorize('home.read_state')
    for action in ['lock.unlock','critical.power_off','files.remove','shell.exec']:
        with pytest.raises(PermissionError):gate.authorize(action,human_confirmation=True)

# Executes the patched auth method in isolation, without importing Torch/audio runtime.
def test_upstream_strict_auth_regression():
    source=(ROOT/'vendor/xiaozhi-server/main/xiaozhi-server/core/websocket_server.py').read_text(encoding='utf-8')
    tree=ast.parse(source);cls=next(x for x in tree.body if isinstance(x,ast.ClassDef) and x.name=='WebSocketServer');method=next(x for x in cls.body if isinstance(x,ast.AsyncFunctionDef) and x.name=='_handle_auth');method.args.args[1].annotation=None
    namespace={'AuthenticationError':ValueError};exec(compile(ast.Module(body=[method],type_ignores=[]),'auth_fixture','exec'),namespace)
    authsource=(ROOT/'vendor/xiaozhi-server/main/xiaozhi-server/core/auth.py').read_text(encoding='utf-8');ns={};exec(compile(authsource,'auth_fixture','exec'),ns);auth=ns['AuthManager']('fixture-only',60)
    owner=types.SimpleNamespace(auth_enable=True,allowed_devices={'device'},auth=auth)
    async def exercise():
        for headers in [{'device-id':'device','client-id':'client'},{'device-id':'other','client-id':'client','authorization':'Bearer '+auth.generate_token('client','other')}]:
            ws=types.SimpleNamespace(request=types.SimpleNamespace(headers=headers))
            with pytest.raises(ValueError):await namespace['_handle_auth'](owner,ws)
        headers={'device-id':'device','client-id':'client','authorization':'Bearer '+auth.generate_token('client','device')}
        await namespace['_handle_auth'](owner,types.SimpleNamespace(request=types.SimpleNamespace(headers=headers)))
        owner.auth_enable=False
        with pytest.raises(ValueError):await namespace['_handle_auth'](owner,types.SimpleNamespace(request=types.SimpleNamespace(headers=headers)))
    asyncio.run(exercise())
    future=int(time.time())+3600;token=auth._sign('client|device|'+str(future))+'.'+str(future)
    assert not auth.verify_token(token,'client','device')
    assert 'Headers: {self.headers}' not in (ROOT/'vendor/xiaozhi-server/main/xiaozhi-server/core/connection.py').read_text(encoding='utf-8')

def test_compose_is_optional_local_no_auth_mounts():
    import yaml
    config=yaml.safe_load((ROOT/'compose.yaml').read_text(encoding='utf-8'));svc=config['services']['brain']
    assert svc['ports']==['127.0.0.1:18781:18781']
    assert svc['restart']=='unless-stopped' and svc['profiles']==['mock-container']
    assert not any(name in str(svc['volumes']) for name in ['.codex','.cursor','.gemini','host.docker.internal'])
