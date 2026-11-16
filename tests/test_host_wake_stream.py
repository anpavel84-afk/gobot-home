"""Free HOST tests. Fake detectors/accelerated audio are NOT human wake acceptance."""
import asyncio,json,sys,time
from pathlib import Path
from types import SimpleNamespace
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'services/voice'))
from host_wake_core import HostCore,Ring,Detection,StreamFault
from host_vosk import PartialMatcher,VoskDetector,VocabularyUnavailable
from host_stream import HostConnection,StreamOpus,CAPS
from gobot_device_gateway import Gateway,validate_hello,OpusOutput

class Detector:
    def __init__(self,events=None):self.events=events or {};self.calls=0;self.resets=0;self.modes=[]
    def feed(self,pcm,*,speaking):
        self.calls+=1
        if len(self.modes)<100:self.modes.append(speaking)
        return self.events.get(self.calls)
    def reset(self):self.resets+=1

def meta(i,epoch='epoch'):return {'type':'gobot_host_frame','epoch':epoch,'seq':i,'sample_start':i*960,'sample_count':960}
def pcm(i=0):return (i%32767).to_bytes(2,'little')*960

def test_prefix_and_live_join_once():
    c=HostCore(Detector({40:Detection('wake')}),'epoch');expected=[]
    for i in range(45):
        data=pcm(i);expected.append(data);c.feed(meta(i),data)
    assert c.active.start==6400 and c.active.cursor==45*960
    assert bytes(c.active.pcm)==b''.join(expected)[6400*2:]
    assert c.counts['activations']==1 and c.history.size==32000

def test_touch_and_host_deduplicate():
    c=HostCore(Detector({2:Detection('wake')}),'epoch');c.feed(meta(0),pcm())
    assert c.activate('physical_touch')
    assert not c.feed(meta(1),pcm()) and c.counts['activations']==1

@pytest.mark.parametrize('change',[{'epoch':'old'},{'seq':-1},{'seq':True},{'seq':1},{'sample_start':1},{'sample_count':320},{'sample_count':True},{'seq':'0'}])
def test_bad_position_before_detector(change):
    d=Detector();c=HostCore(d,'epoch')
    with pytest.raises(StreamFault):c.feed({**meta(0),**change},pcm())
    assert d.calls==0

@pytest.mark.parametrize('data',[b'',b'x',bytes(1922)])
def test_pcm_bounds(data):
    with pytest.raises(StreamFault):HostCore(Detector(),'epoch').feed(meta(0),data)

def test_gap_invalidates_input():
    c=HostCore(Detector({1:Detection('wake')}),'epoch');c.feed(meta(0),pcm())
    with pytest.raises(StreamFault):c.feed(meta(2),pcm())
    c.close();assert c.active is None and not c.history.blocks

def test_ring_zeroization():
    r=Ring(10);r.append(0,bytes([3,0])*10);old=r.blocks[0]
    r.append(10,bytes([4,0])*10);assert not old.pcm and r.size==10
    current=r.blocks[0];r.clear();assert not current.pcm and not r.blocks

def test_truncation_not_a_command():
    c=HostCore(Detector({1:Detection('wake')}),'epoch',max_input_seconds=1)
    with pytest.raises(StreamFault,match='truncated'):
        for i in range(20):c.feed(meta(i),pcm())
    assert c.finish_input() is None and c.counts['truncated_inputs']==1

def test_local_stop_before_microphone_gate():
    d=Detector({2:Detection('stop')});c=HostCore(d,'epoch');c.playback(True,0)
    c.feed(meta(0),pcm(17));events=c.feed(meta(1),pcm(18))
    assert d.modes==[True,True] and events[0]['event']=='stop'
    assert c.stop() is None
    with pytest.raises(StreamFault):c.stop_ack(events[0]['command_id'],0)
    c.stop_ack(events[0]['command_id'],1);assert c.stop_pending is None
    assert events[0]['provider_close_confirmed'] is False

def test_ordinary_voice_does_not_interrupt():
    c=HostCore(Detector({1:Detection('wake')}),'epoch');c.playback(True,0)
    assert not c.feed(meta(0),pcm()) and c.active is None

def test_reconnect_erases_history():
    c=HostCore(Detector(),'epoch');c.feed(meta(0),pcm());c.activate('physical_touch');held=c.active;c.close()
    assert not held.pcm and c.closed and not c.history.size
    with pytest.raises(StreamFault):HostCore(Detector(),'new').feed(meta(1),pcm())

@pytest.mark.parametrize('text',['робот','работ','готов','какой бот','погода','гобота','не гоп','он сказал гобот','расскажи про гобот',''])
def test_no_fuzzy_or_substring(text):
    m=PartialMatcher();assert not m.feed(text,speaking=False);assert not m.feed(text,speaking=False)

@pytest.mark.parametrize('text',['Гобот','Габот, какая завтра погода?'])
def test_partial_without_waiting_for_final(text):
    m=PartialMatcher();assert m.feed(text,speaking=False) is None
    assert m.feed(text,speaking=False).kind=='wake';assert m.feed(text,speaking=False) is None

def test_gop_output_state_only():
    m=PartialMatcher();assert not m.feed('гоп',speaking=False);assert not m.feed('гоп',speaking=False)
    m.reset();m.feed('гоп',speaking=True);assert m.feed('гоп',speaking=True).kind=='stop'

def test_vosk_oov_no_forced_grammar(monkeypatch,tmp_path):
    created=[]
    class Model:
        def __init__(self,p):pass
        def vosk_model_find_word(self,w):return 7 if w=='гоп' else -1
    monkeypatch.setitem(sys.modules,'vosk',SimpleNamespace(Model=Model,KaldiRecognizer=lambda *a:created.append(a),SetLogLevel=lambda _:None))
    with pytest.raises(VocabularyUnavailable,match='гобот,габот'):VoskDetector(tmp_path)
    assert not created

HELLO={'type':'hello','transport':'websocket','version':1,'audio_params':{'format':'opus','sample_rate':16000,'channels':1,'frame_duration':60},'host_stream':CAPS}

def packets(n=12):
    encoder=OpusOutput();out=[]
    for _ in range(n):out.extend(encoder.feed(bytes(1920),16000))
    out.extend(encoder.finish());return out

def test_real_codec_30_minutes_audio_accelerated():
    packet=packets(10)[2];decoder=StreamOpus();c=HostCore(Detector(),'epoch');start=time.perf_counter()
    for i in range(30000):c.feed(meta(i),decoder.feed(packet))
    assert decoder.packets==30000 and c.history.size==32000 and c.active is None
    assert decoder.samples<=30000*960 and not hasattr(decoder,'pcm')
    print(json.dumps({'audio_seconds':1800,'wall_seconds':round(time.perf_counter()-start,3),'real_time_soak':False,'physical_device':False,'retained_audio_bytes':c.history.size*2}))
    c.close();decoder.close()

class FakeWS:
    def __init__(self,audio=None,*,caps=True):
        self.stage=0;self.out=[];self.epoch=None;self.session=None;self.closed=False;self.input=[];self.audio=audio or [];self.caps=caps
        self.request=SimpleNamespace(path='/xiaozhi/v1/',headers={'Device-Id':'test-mac','Protocol-Version':'1','Authorization':'Bearer test-token'})
    async def send(self,raw):
        obj=json.loads(raw);self.out.append(obj);self.epoch=obj['epoch'];self.session=obj['session_id']
    async def recv(self):
        await asyncio.sleep(.006)
        if self.stage==0:
            self.stage=1;hello=dict(HELLO)
            if not self.caps:hello.pop('host_stream')
            return json.dumps(hello)
        if self.stage==1:
            self.stage=2
            for i,p in enumerate(self.audio):self.input.extend([json.dumps({**meta(i,self.epoch),'session_id':self.session}),p])
            self.input.append(json.dumps({'type':'gobot_host_mute','epoch':self.epoch,'session_id':self.session,'muted':True}))
            return json.dumps({'type':'gobot_host_ready_ack','epoch':self.epoch,'session_id':self.session,'frame_samples':960})
        if self.input:return self.input.pop(0)
        await asyncio.Event().wait()
    async def close(self,code,reason):self.closed=True;self.close_code=code

def test_actual_codec_connection_free_feedback():
    async def run():
        ws=FakeWS(packets());h=HostConnection(lambda:Detector({3:Detection('wake')}));await h.run(ws,validate_hello)
        events=[x for x in ws.out if x.get('type')=='gobot_host_event']
        assert len(events)==1 and events[0]['event']=='wake' and events[0]['paid_session_opened'] is False
        assert h.stats['provider_calls']==0 and h.last_core.closed and not h.last_core.history.size
        assert 'last_failure_code' not in h.stats,h.stats
    asyncio.run(run())

def test_old_firmware_requires_new_capability():
    async def run():
        ws=FakeWS(caps=False);created=[];h=HostConnection(lambda:created.append(True));await h.run(ws,validate_hello)
        assert not created and h.stats['last_failure_code']=='host_capability_required'
    asyncio.run(run())

@pytest.mark.parametrize('obj',[None,[],1,'x'*4097])
def test_parser_bounds(obj):
    with pytest.raises(StreamFault):HostConnection.parse(obj if isinstance(obj,str) else json.dumps(obj))

def config():return {'device_mac':'test-mac','device_token':'test-token','mode':'realtime_b','host_wake':{'enabled':True,'lan_stream_consent':True,'acceptance_only':True}}

def test_existing_gateway_host_path_does_not_consult_paid_budget(monkeypatch):
    calls=[]
    def deny(*a,**k):calls.append(True);raise AssertionError('paid path called')
    async def run():
        g=Gateway(config(),'fixture-brain-token',client_factory=deny,host_detector_factory=lambda:Detector({3:Detection('wake')}))
        g.save_stats=lambda:None;g.reserve_manual_turn=deny;g.respond=deny
        ws=FakeWS(packets());await g.handle(ws)
        assert not calls and not g.active and any(o.get('event')=='wake' for o in ws.out)
    asyncio.run(run())

@pytest.mark.parametrize('kind',['auth','consent','busy'])
def test_gateway_guards_precede_host_detector(kind):
    async def run():
        cfg=config();created=[];g=Gateway(cfg,'fixture',host_detector_factory=lambda:created.append(True));g.save_stats=lambda:None
        ws=FakeWS()
        if kind=='auth':ws.request.headers['Authorization']='Bearer wrong'
        elif kind=='consent':cfg['host_wake']['lan_stream_consent']=False
        else:g.active=True
        await g.handle(ws);assert not created and ws.closed
    asyncio.run(run())


def test_real_loopback_websocket_same_gateway_no_paid_dependencies():
    from websockets.asyncio.server import serve
    from websockets.asyncio.client import connect
    async def run():
        calls=[];gateway=[]
        def deny(*a,**kw):calls.append(True);raise AssertionError('paid/external path forbidden')
        async def handler(ws):
            g=Gateway(config(),'fixture',client_factory=deny,host_detector_factory=lambda:Detector({3:Detection('wake')}));g.save_stats=lambda:None;g.reserve_manual_turn=deny;g.respond=deny
            gateway.append(g);await g.handle(ws)
        async with serve(handler,'127.0.0.1',0) as server:
            port=server.sockets[0].getsockname()[1]
            async with connect(f'ws://127.0.0.1:{port}/xiaozhi/v1/',additional_headers={'Device-Id':'test-mac','Protocol-Version':'1','Authorization':'Bearer test-token'}) as ws:
                await ws.send(json.dumps(HELLO));hello=json.loads(await ws.recv());ready=json.loads(await ws.recv())
                epoch=ready['epoch'];session=ready['session_id']
                await ws.send(json.dumps({'type':'gobot_host_ready_ack','epoch':epoch,'session_id':session,'frame_samples':960}))
                for i,packet in enumerate(packets(5)):
                    await ws.send(json.dumps({**meta(i,epoch),'session_id':session}));await ws.send(packet);await asyncio.sleep(.06)
                event=json.loads(await asyncio.wait_for(ws.recv(),1));scene=json.loads(await ws.recv())
                assert event['event']=='wake' and not event['conversation_admitted']
                assert scene['payload']['namespace']=='gobot.ui'
                for kind in ('rendered','cue_started'):
                    await ws.send(json.dumps({'type':'gobot_host_ack','epoch':epoch,'session_id':session,'feedback_id':event['feedback_id'],'event':kind}))
                await ws.send(json.dumps({'type':'gobot_host_mute','epoch':epoch,'session_id':session,'muted':True}));await ws.wait_closed()
        assert gateway and not calls and not gateway[0].active
        assert gateway[0].stats['host']['provider_calls']==0
    asyncio.run(run())


def test_stalled_inference_queue_overflow_is_explicit():
    class Slow(Detector):
        def feed(self,*a,**kw):time.sleep(.15);return super().feed(*a,**kw)
    async def run():
        ws=FakeWS(packets(25));h=HostConnection(Slow,max_queue_frames=2)
        await h.run(ws,validate_hello)
        assert h.stats['last_failure_code']=='host_queue_overflow'
        assert h.last_core.closed and h.last_core.history.size==0
    asyncio.run(run())


def test_old_receipt_does_not_resume_output():
    c=HostCore(Detector(),'epoch');c.playback(True,0);event=c.stop()
    with pytest.raises(StreamFault):c.playback(False,0)
    with pytest.raises(StreamFault):c.stop_ack('wrong',event['output_epoch'])
    assert c.stop_pending==event['command_id']


@pytest.mark.parametrize('field,value',[('version',True),('frame_sequence',1),('local_wake_enabled',0),('local_feedback',1)])
def test_capability_types_not_truthy_aliases(field,value):
    class WrongCaps(FakeWS):
        async def recv(self):
            raw=await super().recv()
            if self.stage==1:
                data=json.loads(raw);data['host_stream']={**CAPS,field:value};return json.dumps(data)
            return raw
    async def run():
        seen=[];h=HostConnection(lambda:seen.append(True));await h.run(WrongCaps(),validate_hello)
        assert not seen and h.stats['last_failure_code']=='host_capability_required'
    asyncio.run(run())


def test_queue_age_failure_not_silent_input_skip():
    class Clock:
        def __init__(self):self.calls=0
        def __call__(self):self.calls+=1;return self.calls*.3
    async def run():
        h=HostConnection(Detector,clock=Clock());await h.run(FakeWS(packets(4)),validate_hello)
        assert h.stats['last_failure_code']=='host_queue_stale'
        assert h.last_core.closed and h.last_core.history.size==0
    asyncio.run(run())


def test_native_decoder_does_not_accept_20ms_as_60ms():
    import av
    from fractions import Fraction
    import numpy as np
    e=av.CodecContext.create('libopus','w');e.sample_rate=16000;e.layout='mono';e.format='s16';e.time_base=Fraction(1,16000)
    e.options={'frame_duration':'20','application':'voip'};e.open()
    frame=av.AudioFrame.from_ndarray(np.zeros((1,320),dtype=np.int16),format='s16',layout='mono');frame.sample_rate=16000;frame.pts=0;frame.time_base=Fraction(1,16000)
    encoded=[bytes(p) for p in e.encode(frame)]+[bytes(p) for p in e.encode(None)]
    with pytest.raises(StreamFault,match='duration_mismatch'):StreamOpus().feed(encoded[0])


def test_boolean_is_not_output_epoch():
    c=HostCore(Detector(),'epoch');c.playback(True,0);event=c.stop()
    with pytest.raises(StreamFault):c.stop_ack(event['command_id'],True)
    assert c.stop_pending is not None


def test_host_launcher_does_not_require_brain_or_livekit_secrets(monkeypatch,tmp_path):
    import gobot_device_gateway as module
    cfg=config();cfg.update(bind='192.168.1.2',port=18789,url='wss://192.168.1.2:18789/xiaozhi/v1/',brain_url='http://127.0.0.1:18781',continuous_live=True)
    path=tmp_path/'gateway.json';path.write_text(json.dumps(cfg));tokens=[]
    class StopBeforeBind(Exception):pass
    class NoServer:
        async def __aenter__(self):raise StopBeforeBind()
        async def __aexit__(self,*a):return False
    class TestGateway:
        def __init__(self,conf,token):tokens.append(token)
        async def handle(self,*a):pass
    class TLS:
        def __init__(self,*a):pass
        def load_cert_chain(self,*a):pass
    monkeypatch.setattr(module,'ROOT',tmp_path);monkeypatch.setattr(module,'PRIVATE',tmp_path)
    monkeypatch.setattr(module,'Gateway',TestGateway);monkeypatch.setattr(module.ssl,'SSLContext',TLS)
    monkeypatch.setattr(module,'serve',lambda *a,**k:NoServer())
    monkeypatch.setattr(sys,'argv',['gateway','--config',str(path)])
    with pytest.raises(StopBeforeBind):asyncio.run(module.main())
    assert tokens==[''] and not (tmp_path/'run/keys.json').exists()
