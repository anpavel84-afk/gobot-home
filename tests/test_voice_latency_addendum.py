"""L0/L1 free acceptance: numeric traces, scopes, no invented acoustic evidence."""
import asyncio, json, sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'services/voice'))
from voice_latency import LatencyTrace
from prepared_b import PreparedB,PreparedScope,ReadyProof,CloseProof,compare_manifest,PARITY_FIELDS

class Clock:
    def __init__(self):self.t=100.
    def __call__(self):return self.t

def dev(trace,event,us,seq=0,kind='unknown',turn=0):
    return {'type':'gobot_latency','session_id':'session','trace_id':trace.trace_id,'clock_epoch':'boot1',
            'seq':seq,'device_us':us,'event':event,'audio_kind':kind,'turn':turn}

def test_no_cross_clock_subtraction():
    t=LatencyTrace(clock=Clock());t.mark('provider_audio_committed')
    t.device_event(dev(t,'playback_started',900000000,kind='provider_reply'),session_id='session')
    assert t.summary()['metrics']['0']['gateway_commit_to_first_audio']['status']=='NOT_MEASURED'
    assert t.summary()['metrics']['0']['speech_end_to_meaningful_audible_reply']['status']=='NOT_MEASURED'

def test_device_same_clock_and_vad_not_acoustic_truth():
    t=LatencyTrace();t.device_event(dev(t,'mic_last_speech',100000,0),session_id='session')
    t.device_event(dev(t,'playback_started',375000,1,'provider_reply'),session_id='session')
    m=t.summary()['metrics']['0']
    assert m['vad_end_to_provider_playback_device']['ms']==275
    assert m['vad_end_to_provider_playback_device']['start_evidence']=='device_vad_estimate'
    assert m['speech_end_to_meaningful_audible_reply']['status']=='NOT_MEASURED'

@pytest.mark.parametrize('kind',['earcon','fixture','unknown'])
def test_tone_and_packet_not_meaningful_response(kind):
    t=LatencyTrace();t.device_event(dev(t,'mic_last_speech',100000),session_id='session')
    t.device_event(dev(t,'playback_started',120000,1,kind),session_id='session')
    assert t.summary()['metrics']['0']['vad_end_to_provider_playback_device']['status']=='NOT_MEASURED'
    assert not t.summary()['physical_latency_accepted']

@pytest.mark.parametrize('patch',[{'trace_id':'other'},{'session_id':'old'},{'clock_epoch':''},
 {'seq':True},{'device_us':True},{'device_us':-1},{'device_us':2**53},
 {'event':'secret_user_text'},{'audio_kind':'human_verified_reply'},{'transcript':'private'}])
def test_invalid_device_evidence(patch):
    t=LatencyTrace()
    with pytest.raises(ValueError):t.device_event({**dev(t,'capture_begin',100),**patch},session_id='session')

def test_stale_and_changed_clock_fail():
    t=LatencyTrace();event=dev(t,'capture_begin',100)
    t.device_event(event,session_id='session')
    with pytest.raises(ValueError):t.device_event(event,session_id='session')
    with pytest.raises(ValueError):t.device_event({**event,'seq':1,'clock_epoch':'boot2'},session_id='session')

def test_trace_bound_no_speech_content():
    c=Clock();t=LatencyTrace(clock=c,limit=16)
    for n in range(32):
        t.mark('gateway_first_frame',turn=n);c.t+=.01
    assert len(t.stamps)==16 and t.overflow==16
    for n in range(10000):t.gauge('input_backlog_ms',n)
    assert len(t.gauges)==1 and t.gauges['input_backlog_ms']['max']==9999
    with pytest.raises(ValueError):t.gauge('user_text',1)

@pytest.mark.parametrize('n',[True,float('nan'),float('inf'),-1])
def test_invalid_clock_or_gauge(n):
    t=LatencyTrace()
    with pytest.raises(ValueError):t.mark('capture_begin',milliseconds=n)
    with pytest.raises(ValueError):t.gauge('input_backlog_ms',n)

def test_remote_clock_must_be_explicit():
    with pytest.raises(ValueError):LatencyTrace().mark('playback_started',domain='device')

def test_turn_landmarks_do_not_mix():
    c=Clock();t=LatencyTrace(clock=c)
    for n in range(2):
        t.input_started();c.t+=.1;t.mark('provider_audio_committed')
        t.response('response_'+str(n));c.t+=.2;t.mark('provider_first_output_audio',kind='provider_reply')
    assert len(t.summary()['metrics'])==2
    assert all(m['gateway_commit_to_first_audio']['ms']==200 for m in t.summary()['metrics'].values())

class Admission:
    def __init__(self,allowed=True):self.allowed=allowed;self.calls=[]
    async def claim(self,scope,operation_id,**kw):
        self.calls.append((scope,operation_id,kw))
        if not self.allowed:raise PermissionError('no_extra_owner_grant')
        return 'fixture-finite-claim'
class Factory:
    def __init__(self,proof=None,close=None):
        self.calls=[];self.proof=proof or ReadyProof(True,True,True,True,True,True,'gpt-realtime-2.1-mini','marin')
        self.close_proof=close or CloseProof(True,True,False)
    async def open(self,*args):self.calls.append('open');return 'fixture-handle',self.proof
    async def activate(self,*args):self.calls.append('activate');return True
    async def close(self,*args):self.calls.append('close');return self.close_proof
SCOPE=PreparedScope('fixture-device','fixture-profile','fixture-transport')

def test_default_cannot_open_prepared_session():
    async def run():
        f=Factory();p=PreparedB(SCOPE,factory=f)
        with pytest.raises(PermissionError):await p.prepare()
        assert not f.calls and p.input_frame(bytes(1920)) is None
    asyncio.run(run())

def test_exhausted_or_wrong_grant_before_factory():
    async def run():
        f=Factory();a=Admission(False);p=PreparedB(SCOPE,factory=f,admission=a)
        with pytest.raises(PermissionError):await p.prepare()
        assert not f.calls and a.calls[0][2]['purpose']=='B_READY_BEFORE_TOUCH'
    asyncio.run(run())

def test_ready_without_ambient_or_response_and_one_activation():
    async def run():
        f=Factory();a=Admission();p=PreparedB(SCOPE,factory=f,admission=a)
        await p.prepare();original=b'\1\0'*960
        for _ in range(30):assert p.input_frame(original) is None
        assert f.calls==['open'] and p.state=='READY'
        await p.activate(SCOPE,'touch1');assert p.input_frame(original)==original
        with pytest.raises(RuntimeError):await p.activate(SCOPE,'touch2')
        await p.close();await p.close()
        assert f.calls==['open','activate','close'] and len(a.calls)==1
        assert p.close_proof.provider_close_confirmed and not p.close_proof.usage_final_received
    asyncio.run(run())

@pytest.mark.parametrize('field',['session_ack','sdp_ack','media_ready','configuration_ack','input_disabled','transcription_disabled'])
def test_readiness_requires_all_actual_acknowledgements(field):
    async def run():
        from dataclasses import replace
        f=Factory();f.proof=replace(f.proof,**{field:False});p=PreparedB(SCOPE,factory=f,admission=Admission())
        with pytest.raises(ValueError):await p.prepare()
        assert f.calls==['open','close'] and p.input_frame(bytes(1920)) is None
    asyncio.run(run())

def test_expired_prepared_not_reused_or_refunded():
    async def run():
        c=Clock();f=Factory(close=CloseProof(True,False,False));p=PreparedB(SCOPE,factory=f,admission=Admission(),clock=c,ready_ttl=2.)
        await p.prepare();c.t+=3
        with pytest.raises(TimeoutError):await p.activate(SCOPE,'late')
        assert p.state=='UNCONFIRMED' and p.claim and not p.close_proof.provider_close_confirmed
        with pytest.raises(RuntimeError):await p.prepare()
    asyncio.run(run())

def test_profile_change_cannot_activate():
    async def run():
        f=Factory();p=PreparedB(SCOPE,factory=f,admission=Admission());await p.prepare()
        with pytest.raises(PermissionError):await p.activate(PreparedScope('other','fixture-profile','fixture-transport'),'x')
        assert f.calls==['open'];await p.close()
    asyncio.run(run())

def test_parity_is_required_not_guessed():
    assert not compare_manifest({}, {})['comparable']
    a={k:'fixture' for k in PARITY_FIELDS};assert compare_manifest(a,a)['comparable']
    assert compare_manifest(a,{**a,'voice':'different'})['different']==['voice']


def test_streaming_speech_backlog_instrumentation_not_extra_wait():
    from spotpear_live import StreamingSpeech
    async def run():
        c=StreamingSpeech();c.latency=LatencyTrace();c.feed(bytes(1920))
        assert c.latency.gauges['input_backlog_ms']['last']==60
        f=await c.recv();assert f.samples==320 and len(c.buffer)==1280
        c.stop()
    asyncio.run(run())


def test_firmware_output_write_is_proxy_not_acoustic_reply():
    trace = LatencyTrace()
    trace.device_event(dev(trace, 'mic_last_speech', 100_000, 0),
                       session_id='session')
    for sequence, (stage, microseconds) in enumerate([
        ('output_packet_received', 310_000),
        ('output_write_enter', 320_000),
        ('output_write_return', 331_000),
        ('output_tasks_drained', 720_000),
    ], start=1):
        trace.device_event(dev(trace, stage, microseconds, sequence,
                               kind='provider_reply'), session_id='session')
    metrics = trace.summary()['metrics']['0']
    assert metrics['device_vad_end_to_output_write_proxy']['ms'] == 220
    assert metrics['device_output_write_to_tasks_drained_proxy']['ms'] == 400
    assert metrics['speech_end_to_meaningful_audible_reply']['status'] == 'NOT_MEASURED'
    assert metrics['vad_end_to_provider_playback_device']['status'] == 'NOT_MEASURED'
    assert trace.summary()['physical_latency_accepted'] is False


def test_fixture_output_write_never_counts_as_provider_reply():
    trace = LatencyTrace()
    trace.device_event(dev(trace, 'mic_last_speech', 120_000, 0),
                       session_id='session')
    trace.device_event(dev(trace, 'output_write_enter', 130_000, 1,
                           kind='fixture'), session_id='session')
    assert trace.summary()['metrics']['0']['device_vad_end_to_output_write_proxy']['status'] == 'NOT_MEASURED'
    assert trace.summary()['physical_latency_accepted'] is False
