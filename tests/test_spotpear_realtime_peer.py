"""Two local aiortc peers + existing loopback LiveKit. Mock Brain, no OpenAI."""
import asyncio,json,os,sys
from fractions import Fraction
from pathlib import Path
import httpx,numpy as np,pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'services/voice'))
from aiortc import AudioStreamTrack,RTCConfiguration,RTCPeerConnection,RTCSessionDescription
import av
from spotpear_live import StreamingSpeech
from spotpear_realtime import realtime_turn
from gobot_device_gateway import OpusOutput

@pytest.mark.skipif(not os.environ.get('GOBOT_LOCAL_LIVEKIT_TEST'),reason='Requires loopback LiveKit, no provider')
@pytest.mark.parametrize('scenario',['conversation','stop','network_loss','missing_playback_ack'])
def test_two_way_b_listen_think_speak_drain_listen(scenario):
    async def run():
        remote=RTCPeerConnection(RTCConfiguration(iceServers=[]))
        capture=StreamingSpeech();capture.deferred_start=True
        input_received=asyncio.Event();tone_on=asyncio.Event();tone_done=asyncio.Event()
        media_ready=asyncio.Event();followup=asyncio.Event();commands=[];packets=[];tasks=[];controls=[]
        last_packet=[0.];quiet_during_output=[0]
        operation=[None];output_seen=asyncio.Event();offers=[]
        class Tone(AudioStreamTrack):
            position=0;start=None;played=0
            async def recv(self):
                loop=asyncio.get_running_loop()
                if self.start is None:self.start=loop.time()
                await asyncio.sleep(max(0,self.start+self.position/16000-loop.time()))
                audible=tone_on.is_set() and self.played<20
                raw=(4000*np.sin((np.arange(320)+self.position)*.11) if audible else np.zeros(320)).astype(np.int16)
                if audible:
                    self.played+=1
                    if self.played==20:tone_done.set()
                frame=av.AudioFrame.from_ndarray(raw.reshape(1,-1),format='s16',layout='mono')
                frame.sample_rate=16000;frame.pts=self.position;frame.time_base=Fraction(1,16000);self.position+=320
                return frame
        @remote.on('track')
        def received(track):
            async def consume():
                while True:
                    frame=await track.recv();peak=np.max(np.abs(frame.to_ndarray().astype(float)))
                    if peak>100:input_received.set()
                    elif tone_on.is_set():quiet_during_output[0]+=1
            tasks.append(asyncio.create_task(consume()))
        async def handler(request):
            assert request.url.host=='127.0.0.1' and '/voice-ab/b/' in request.url.path
            if request.method=='GET':
                class Events(httpx.AsyncByteStream):
                    async def __aiter__(self):
                        serial=0
                        def event(kind,**data):
                            nonlocal serial
                            serial+=1
                            return ('data: '+json.dumps({'serial':serial,'session_id':'local-b','type':kind,'data':data})+'\n\n').encode()
                        await asyncio.wait_for(input_received.wait(),5)
                        yield event('audio_diagnostic',stage='server_audio_committed')
                        yield event('processing',response_id='response-1')
                        tone_on.set()
                        if scenario=='network_loss':
                            await asyncio.wait_for(output_seen.wait(),5)
                            raise httpx.ReadError('synthetic control loss')
                        await asyncio.wait_for(tone_done.wait(),5)
                        yield event('generation_done',response_id='response-1',status='completed')
                        yield event('playback_buffer_stopped',response_id='response-1')
                        await asyncio.wait_for(followup.wait(),6)
                        yield event('closed',reason='user_stop')
                return httpx.Response(200,stream=Events())
            body=json.loads(request.content)
            if request.url.path.endswith('/command'):
                commands.append(body)
                if body['action']=='followup' and sum(c['action']=='followup' for c in commands)==2:followup.set()
                return httpx.Response(200,json={'accepted':True})
            assert not body['remember'] and body['requested_model']=='gpt-realtime-2.1-mini'
            offers.append(body)
            await remote.setRemoteDescription(RTCSessionDescription(body['sdp'],'offer'))
            remote.addTrack(Tone());await remote.setLocalDescription(await remote.createAnswer())
            return httpx.Response(200,json={'sdp':remote.localDescription.sdp,'session_id':'local-b',
                'model':'gpt-realtime-2.1-mini','voice':'marin','configuration_confirmed':True})
        async def send(control):
            controls.append(control)
            if control['type']=='gobot_media_ready':media_ready.set()
        async def send_audio(packet):
            packets.append(packet);last_packet[0]=asyncio.get_running_loop().time()
            capture.playing=scenario!='missing_playback_ack';capture.activity_at=last_packet[0]
            if len(packets)>=3:output_seen.set()
            if scenario=='stop' and len(packets)==3:asyncio.get_running_loop().call_soon(operation[0].cancel)
        async def microphone():
            await media_ready.wait()
            while True:
                capture.feed((2500*np.sin(np.arange(320)*.2)).astype('<i2').tobytes())
                await asyncio.sleep(.02)
        async def hardware_activity():
            while True:
                now=asyncio.get_running_loop().time()
                capture.activity_at=now
                capture.playing=scenario!='missing_playback_ack' and bool(last_packet[0] and now-last_packet[0]<.2)
                await asyncio.sleep(.08)
        tasks.extend([asyncio.create_task(microphone()),asyncio.create_task(hardware_activity())])
        settings=json.loads(Path(os.environ['GOBOT_LOCAL_LIVEKIT_TEST']).read_text())
        config={'device_id':'board','conversation_id':'local-b-topic','brain_url':'http://127.0.0.1:18781',
            'hardware_realtime_consent':True,'livekit_settings':settings}
        try:
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                operation[0]=asyncio.create_task(realtime_turn(client,config,{},capture,'local-b',send,send_audio,OpusOutput()))
                if scenario=='stop':
                    with pytest.raises(asyncio.CancelledError):await asyncio.wait_for(operation[0],20)
                elif scenario=='network_loss':
                    with pytest.raises(httpx.ReadError):await asyncio.wait_for(operation[0],20)
                elif scenario=='missing_playback_ack':
                    with pytest.raises(ValueError,match='playback_ack_missing'):await asyncio.wait_for(operation[0],20)
                else:await asyncio.wait_for(operation[0],20)
            actions=[c['action'] for c in commands]
            assert len(offers)==1 and actions[-1]=='close' and actions.count('close')==1
            if scenario=='conversation':
                assert actions==['followup','playback_started','playback_stopped','followup','close']
                assert packets and quiet_during_output[0]>5
                assert [c['state'] for c in controls if c['type']=='tts']==['start','stop']
            else:assert actions.count('followup')==1
        finally:
            for task in tasks:task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True);await remote.close()
    asyncio.run(run())
