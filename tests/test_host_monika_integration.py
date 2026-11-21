"""Protocol-only compatibility: fake WakeEvents, real Opus, no acoustic trials."""
import asyncio,json,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'services'/'voice'))
from host_wake_contract import WakeEvent
from gobot_device_gateway import Gateway
from host_downlink import fixture_packets
from test_host_audio_downlink import HELLO,uplink_packets

class EventFixture:
    def __init__(self):self.suppress_events=False;self.endpoint_sample=-1
    def reset(self):self.endpoint_sample=-1
    def feed_chunk(self,chunk):
        seq=chunk.sample_index//960
        if seq in (25,90):self.endpoint_sample=chunk.end_sample_index
        if seq in (4,5,70,71) and not self.suppress_events:
            return WakeEvent(chunk.stream_epoch,chunk.end_sample_index,'monika','contract-fixture',time.monotonic_ns())
        return None

def test_monika_event_immediate_feedback_preroll_and_two_answers():
    from websockets.asyncio.server import serve
    from websockets.asyncio.client import connect
    async def run():
        holders=[];captures=[]
        def forbidden(*a,**kw):raise AssertionError('paid_calls_forbidden')
        def answer(pcm):captures.append(len(pcm));return fixture_packets()
        cfg={'device_mac':'fixture','device_token':'fixture','mode':'hardware_test',
             'host_wake':{'enabled':True,'lan_stream_consent':True,'acceptance_only':True,
                          'free_downlink_fixture':False,'monika_trial':True}}
        async def handler(ws):
            g=Gateway(cfg,'NEVER',client_factory=forbidden,host_detector_factory=EventFixture)
            g.save_stats=lambda:None;g.respond=forbidden;g.reserve_manual_turn=forbidden
            g.host_local_command_responder=answer;holders.append(g)
            await g.handle(ws)
        async with serve(handler,'127.0.0.1',0) as server:
            port=server.sockets[0].getsockname()[1]
            async with connect(f'ws://127.0.0.1:{port}/xiaozhi/v1/',additional_headers={
                    'Device-Id':'fixture','Protocol-Version':'1','Authorization':'Bearer fixture'}) as ws:
                await ws.send(json.dumps(HELLO));await ws.recv();ready=json.loads(await ws.recv())
                def msg(t,**kw):return {'type':t,'session_id':ready['session_id'],'epoch':ready['epoch'],**kw}
                lock=asyncio.Lock()
                async def send(data,binary=None):
                    async with lock:
                        await ws.send(json.dumps(data))
                        if binary is not None:await ws.send(binary)
                await send(msg('gobot_host_ready_ack',frame_samples=960))
                end=asyncio.Event()
                async def microphone():
                    packets=uplink_packets(120)
                    for seq,packet in enumerate(packets):
                        if end.is_set():break
                        await send(msg('gobot_host_frame',seq=seq,sample_start=seq*960,sample_count=960),packet)
                        await asyncio.sleep(.04)
                mic=asyncio.create_task(microphone())
                wakes=0;outputs=0;ids=[];seen=0;playback=None
                async with asyncio.timeout(10):
                    while outputs<2:
                        event=json.loads(await ws.recv());kind=event['type']
                        if kind=='gobot_host_event':
                            assert event['event']=='wake' and event['source']=='host_wake'
                            wakes+=1
                            # r3 may emit finish from an old touch clock; ignore until actual endpoint.
                            await send(msg('gobot_host_finish'))
                            for ack in ('rendered','cue_started'):
                                await send(msg('gobot_host_ack',feedback_id=event['feedback_id'],event=ack))
                            if wakes==1:assert event['prefix_start']==0
                        elif kind=='gobot_host_output_start':
                            playback=event['playback_id'];ids.append(playback);seen=0
                        elif kind=='gobot_host_output_frame':
                            assert event['seq']==seen;seen+=1
                            assert isinstance(await ws.recv(),bytes)
                            if seen==1:await send(msg('gobot_host_playback',playback_id=playback,output_epoch=0,playing=True))
                        elif kind=='gobot_host_output_end':
                            await send(msg('gobot_host_playback',playback_id=playback,output_epoch=0,playing=False));outputs+=1
                        elif kind in ('custom','gobot_host_idle'):pass
                        else:raise AssertionError(kind)
                end.set();await mic;await asyncio.sleep(.12)
                await send(msg('gobot_host_mute',muted=True));await ws.wait_closed()
        stats=holders[0].stats['host']
        assert wakes==2 and len(set(ids))==2
        assert len(captures)==2 and captures[0]==26*1920
        assert stats['local_command_recognized']==2 and stats['completed_replies']==2
        assert stats['ignored_early_device_finishes']==2
        assert stats['screen_acks']==stats['cue_acks']==2
        assert stats['provider_calls']==0 and 'last_failure_code' not in stats,stats
    asyncio.run(run())
