import asyncio,ast,json,sys,types,io,wave
from pathlib import Path
import pytest
from gobot.metrics import StageMetrics,percentiles
from gobot.agents import AppServerTransport
ROOT=Path(__file__).resolve().parents[1]
def test_unknown_real_latency_is_not_invented():
    m=StageMetrics();m.mark('llm_first_token');s=m.snapshot();assert s['stt'] is None and s['first_opus_playback'] is None
    assert percentiles([1,2,3,4])=={'n':4,'p50':2.5,'p95':4}
def test_appserver_transport_wire_no_mcp_field():
    async def exercise():
        reader=asyncio.StreamReader()
        class Writer:
            def write(self,data):
                obj=json.loads(data);assert 'jsonrpc' not in obj
                if 'id' in obj and 'method' in obj:reader.feed_data(json.dumps({'id':obj['id'],'result':{'ok':True}}).encode()+b'\n')
            async def drain(self):pass
            def close(self):pass
        rpc=AppServerTransport(reader,Writer());await rpc.start()
        assert await rpc.request('initialize',{})=={'ok':True}
        reader.feed_data(b'{"method":"notice","params":{}}\n');reader.feed_eof()
        assert [o async for o in rpc.events()]==[{'method':'notice','params':{}}]
        await rpc.close()
    asyncio.run(exercise())
def test_generated_upstream_config_is_safe():
    import yaml
    voice=ROOT/'vendor/xiaozhi-server/main/xiaozhi-server'
    base=yaml.safe_load((voice/'config.yaml').read_text(encoding='utf-8'))
    assert base['plugins']=={} and base['LLM']=={} and base['ASR']=={} and base['TTS']=={}
    assert not base['manager-api'] and base['mcp_endpoint'] is None
    # Do not load/print the ignored secret override in a test assertion.
    for category in ['asr','tts']:
        for name in ['gobot_mock','gobot_openai_ru']:assert (voice/f'core/providers/{category}/{name}.py').exists()
def test_voice_mock_tts_real_interface_returns_wav(monkeypatch):
    module=types.ModuleType('core.providers.tts.base')
    class Base:
        def __init__(self,*a):pass
    module.TTSProviderBase=Base
    monkeypatch.setitem(sys.modules,'core',types.ModuleType('core'))
    monkeypatch.setitem(sys.modules,'core.providers',types.ModuleType('core.providers'))
    monkeypatch.setitem(sys.modules,'core.providers.tts',types.ModuleType('core.providers.tts'))
    monkeypatch.setitem(sys.modules,'core.providers.tts.base',module)
    ns={};exec(compile((ROOT/'services/voice/providers/tts/gobot_mock.py').read_text(encoding='utf-8'),'mock_tts','exec'),ns)
    data=asyncio.run(ns['TTSProvider']({},True).text_to_speak('Русская fixture',None))
    with wave.open(io.BytesIO(data)) as wav:assert wav.getframerate()==24000 and wav.getnchannels()==1 and wav.getnframes()==1440

@pytest.mark.parametrize('url',['http://127.0.0.1:18782@evil.test','http://127.0.0.1:18782/path','http://127.0.0.1:18782?next=evil'])
def test_bridge_origin_confusion_denied(settings,url):
    settings.bridge_url=url
    with pytest.raises(ValueError):settings.validate()
def test_second_opinion_explicit_mock_cannot_spend(settings,monkeypatch):
    from gobot.brain import Service
    from gobot.models import ChatRequest
    import gobot.providers as providers
    def deny_network(*args,**kwargs):raise AssertionError('Explicit mock must not create API client')
    monkeypatch.setattr(providers.httpx,'AsyncClient',deny_network)
    settings.fast_provider='openai';settings.api_key='fixture-key';settings.api_model='fixture-model';settings.allow_paid=True
    async def exercise():
        service=Service(settings);req=ChatRequest(text='Спроси ChatGPT, как он думает об этом',provider='mock')
        await service.prepare(req);items=[item async for item in service.events(req)]
        assert items[-1].type=='final' and items[-1].data['provider']=='mock'
        assert len(items[-1].data['trace'])==1
    asyncio.run(exercise())
def test_same_conversation_concurrent_turn_rejected(settings):
    from gobot.memory import Memory,Conflict
    from gobot.models import ChatRequest
    m=Memory(settings.db);r=ChatRequest(text='first',conversation_id='shared-turn');m.start(r)
    with pytest.raises(Conflict):m.start(ChatRequest(text='second',conversation_id='shared-turn'))

def test_image_origin_authenticated_mint_and_delivery(settings):
    from fastapi.testclient import TestClient
    from PIL import Image
    from gobot.voice_mock import image_app
    out=io.BytesIO();Image.new('RGB',(240,240),'navy').save(out,format='JPEG');data=out.getvalue()
    with TestClient(image_app(settings)) as client:
        assert client.post('/api/v1/images',content=data,headers={'Content-Type':'image/jpeg'}).status_code==401
        response=client.post('/api/v1/images',content=data,headers={'Content-Type':'image/jpeg','Authorization':'Bearer '+settings.api_token})
        assert response.status_code==200
        key=response.json()['url'].rsplit('/',1)[1];download=client.get('/images/'+key)
        assert download.content==data and download.headers['content-type']=='image/jpeg'
        assert int(download.headers['content-length'])==len(data)
        assert client.post('/api/v1/images',content=b'x'*65537,headers={'Content-Type':'image/jpeg','Authorization':'Bearer '+settings.api_token}).status_code==413
