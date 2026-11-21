"""Offline tests: real Opus codec, isolated synthetic audio, no provider calls."""
import asyncio
import importlib.util
import io
import json
from pathlib import Path
import wave
from types import SimpleNamespace
import numpy as np
import pytest
from websockets.datastructures import Headers

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('gobot_device_gateway',ROOT/'services/voice/gobot_device_gateway.py')
g=importlib.util.module_from_spec(spec);spec.loader.exec_module(g)
CONFIG={'device_mac':'02:00:00:00:00:01','device_token':'a'*64,'device_id':'spotpear-test',
        'conversation_id':'test-conversation','brain_url':'http://127.0.0.1:18781','mode':'hardware_test'}


def headers(**updates):
    d={'Device-Id':CONFIG['device_mac'],'Protocol-Version':'1','Authorization':'Bearer '+CONFIG['device_token']}
    d.update(updates);return Headers(d)


def test_auth_strict():
    assert g.authorize(headers(),CONFIG)
    assert not g.authorize(headers(**{'Authorization':'Bearer '+'b'*64}),CONFIG)
    assert not g.authorize(headers(**{'Device-Id':'other'}),CONFIG)
    assert not g.authorize(headers(**{'Protocol-Version':'3'}),CONFIG)
    duplicate=headers();duplicate['Authorization']='evil'
    assert not g.authorize(duplicate,CONFIG)


def test_hello_strict():
    hello={'type':'hello','version':1,'transport':'websocket','audio_params':{'format':'opus','sample_rate':16000,'channels':1,'frame_duration':60}}
    assert g.validate_hello(hello)
    for key,value in [('format','pcm'),('sample_rate',48000),('channels',2),('frame_duration',20)]:
        changed={**hello,'audio_params':{**hello['audio_params'],key:value}}
        assert not g.validate_hello(changed)
    assert not g.validate_hello({})


@pytest.mark.parametrize('rate',[16000,22050,24000,44100,48000])
def test_actual_opus_roundtrip(rate):
    samples=np.arange(rate,dtype=np.float32)
    pcm=(np.sin(samples*2*np.pi*440/rate)*6000).astype('<i2').tobytes()
    encoder=g.OpusOutput();packets=[]
    for start in range(0,len(pcm),4096):packets.extend(encoder.feed(pcm[start:start+4096],rate))
    packets.extend(encoder.finish());assert encoder.finish()==[]
    assert 16<=len(packets)<=19
    assert all(0<len(p)<=4096 for p in packets)
    decoder=g.OpusInput()
    for packet in packets:decoder.feed(packet)
    with wave.open(io.BytesIO(decoder.wav())) as wav:
        assert wav.getframerate()==16000 and wav.getnchannels()==1 and wav.getsampwidth()==2
        out=np.frombuffer(wav.readframes(wav.getnframes()),dtype='<i2').astype(float)
    assert 15000<=len(out)<=18000
    assert np.sqrt(np.mean(out*out))>1000


def test_codec_bounds():
    decoder=g.OpusInput()
    with pytest.raises(ValueError):decoder.feed(b'x'*4097)
    with pytest.raises(ValueError):decoder.wav()
    output=g.OpusOutput()
    with pytest.raises(ValueError):output.feed(b'x',24000)
    with pytest.raises(ValueError):output.feed(b'xx',12345)
    output.feed(b'\x00'*2048,24000)
    with pytest.raises(ValueError):output.feed(b'\x00'*2048,16000)


class FakeWS:
    def __init__(self,messages,header=None,path='/xiaozhi/v1/'):
        self.request=SimpleNamespace(headers=header or headers(),path=path)
        self.messages=iter(messages);self.sent=[];self.closed=[]
    def __aiter__(self):return self
    async def __anext__(self):
        try:return next(self.messages)
        except StopIteration:raise StopAsyncIteration
    async def send(self,value):self.sent.append(value)
    async def close(self,*args):self.closed.append(args)


def test_rejects_audio_without_listen(tmp_path,monkeypatch):
    monkeypatch.setattr(g,'PRIVATE',tmp_path)
    gateway=g.Gateway(CONFIG,'not-a-real-brain-key')
    ws=FakeWS([b'\xf8\xff\xfe'])
    asyncio.run(gateway.handle(ws))
    assert ws.closed and gateway.stats['errors']==1
    assert not gateway.active


def test_rejects_unauthorized(tmp_path,monkeypatch):
    monkeypatch.setattr(g,'PRIVATE',tmp_path)
    gateway=g.Gateway(CONFIG,'not-a-real-brain-key')
    ws=FakeWS([],header=headers(**{'Authorization':'bad'}))
    asyncio.run(gateway.handle(ws))
    assert ws.closed==[(1008,'Unauthorized device')]
    assert gateway.stats['accepted']==0


def test_quota_survives_restart(tmp_path,monkeypatch):
    monkeypatch.setattr(g,'PRIVATE',tmp_path)
    gateway=g.Gateway({**CONFIG,'max_daily_turns':1},'not-a-real-brain-key')
    gateway.reserve_manual_turn()
    second=g.Gateway({**CONFIG,'max_daily_turns':1},'not-a-real-brain-key')
    with pytest.raises(ValueError,match='hardware_daily_turn_limit'):second.reserve_manual_turn()
    assert json.loads((tmp_path/'hardware-usage.json').read_text())['turns']==1


def test_paid_path_fails_closed(tmp_path,monkeypatch):
    monkeypatch.setattr(g,'PRIVATE',tmp_path)
    gateway=g.Gateway({**CONFIG,'mode':'legacy_a','paid_speech_consent':False},'not-a-real-brain-key')
    async def send(_):raise AssertionError('No network expected')
    with pytest.raises(ValueError,match='permission_required'):
        asyncio.run(gateway.brain_response(FakeWS([]),send,b'', 'test-turn'))
    assert not (tmp_path/'hardware-usage.json').exists()


HELLO = {'type':'hello','transport':'websocket','version':1,
         'audio_params':{'format':'opus','sample_rate':16000,'channels':1,'frame_duration':60}}


def test_missing_protocol_and_stale_session(tmp_path, monkeypatch):
    monkeypatch.setattr(g,'PRIVATE',tmp_path)
    h = headers()
    del h['Protocol-Version']
    assert not g.authorize(h,CONFIG)
    gateway = g.Gateway(CONFIG,'')
    ws = FakeWS([json.dumps(HELLO), json.dumps({'type':'listen','mode':'auto',
               'state':'start','session_id':'old'})])
    asyncio.run(gateway.handle(ws))
    assert ws.closed[0][0] == 1008 and gateway.stats['received_packets'] == 0


def test_completed_hardware_turn_uses_only_local_audio(tmp_path, monkeypatch):
    monkeypatch.setattr(g,'PRIVATE',tmp_path)
    encoder = g.OpusOutput()
    packets = encoder.feed(b'\x00\x00' * 4000, 16000) + encoder.finish()
    class Turn(FakeWS):
        async def __anext__(self):
            item = await super().__anext__()
            if isinstance(item, dict):
                session = json.loads(self.sent[0])['session_id']
                return json.dumps({**item,'session_id':session})
            if item is None:
                async with asyncio.timeout(2):
                    while not any(isinstance(v,str) and json.loads(v).get('state')=='stop' for v in self.sent):
                        await asyncio.sleep(.01)
                raise StopAsyncIteration
            return item
    ws = Turn([json.dumps(HELLO), {'type':'listen','state':'start','mode':'auto'}, *packets,
               {'type':'listen','state':'stop'}, None])
    gateway = g.Gateway(CONFIG,'')
    asyncio.run(gateway.handle(ws))
    assert gateway.stats['completed'] == 1 and gateway.stats['errors'] == 0
    assert any(isinstance(p,bytes) for p in ws.sent)
    assert all(json.loads(p)['type'] != 'stt' for p in ws.sent if isinstance(p,str))
    assert not (tmp_path/'hardware-usage.json').exists()


def test_only_finalized_owned_mode_can_select_a(tmp_path,monkeypatch):
    import httpx
    import uuid
    monkeypatch.setattr(g,'PRIVATE',tmp_path)
    gateway = g.Gateway(CONFIG,'')
    ident = str(uuid.uuid4())
    flow = dict(active=True,mode='legacy',provider_closed=True,mode_conversation_id=ident)
    assert gateway.confirmed_legacy({**flow,'provider_closed':False}) is None
    assert gateway.confirmed_legacy({**flow,'active':False}) is None
    gateway.mode_flow = gateway.confirmed_legacy(flow)
    async def handler(req):
        assert json.loads(req.content) == {'device_id':CONFIG['device_id'],'client_id':CONFIG['device_id'],'action':'activity'}
        return httpx.Response(200,json={**flow,'active':False,'mode':'live'})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            assert await gateway.active_legacy_flow(client) is None
    asyncio.run(run())
    assert gateway.mode_flow is None
