"""Opt-in B transport for Spotpear 0.4.3; never used by C.

Same Opus/WSS + loopback LiveKit + WebRTC path. Input is half-duplex. A
provider response.done or empty host queue never substitutes for device drain.
"""
import asyncio,json,uuid
from contextlib import suppress
import av,numpy as np
from aiortc import RTCPeerConnection,RTCConfiguration,RTCSessionDescription
from spotpear_half_duplex import HalfDuplex
from spotpear_livekit import LocalMediaRelay

class GatedCapture:
    def __init__(self,capture,state):self.capture=capture;self.state=state
    async def recv(self):
        frame=await self.capture.recv() # Always consume; never replay mic captured over output.
        if self.state.input_open:return frame
        muted=av.AudioFrame.from_ndarray(np.zeros((1,frame.samples),dtype=np.int16),format='s16',layout='mono')
        muted.sample_rate=frame.sample_rate;muted.pts=frame.pts;muted.time_base=frame.time_base
        return muted

async def realtime_turn(client,config,headers,capture,ident,send,send_audio,encoder):
    if config.get('hardware_realtime_consent') is not True:raise PermissionError('hardware_b_consent_required')
    if not capture.deferred_start:raise ValueError('hardware_b_requires_media_ready_firmware')
    scope={'device_id':config['device_id']}
    base=config['brain_url']+'/api/v1/voice-ab/b/sessions'
    state=HalfDuplex();peer=RTCPeerConnection(RTCConfiguration(iceServers=[]))
    relay=LocalMediaRelay(config['livekit_settings'],ident)
    tracks=[];peer.on('track',tracks.append)
    tasks=[];attempted=False;last_pcm=0.;flushed=False;started_ack=False;drain_started=0.
    response_ready=asyncio.Event()
    now=lambda:asyncio.get_running_loop().time()
    async def command(action,**kw):
        response=await client.post(f'{base}/{ident}/command',headers=headers,
            json={**scope,'command_id':uuid.uuid4().hex,'action':action,**kw})
        response.raise_for_status();return response.json()
    async def delivered(pcm):
        if state.state!='Speaking':return
        for packet in encoder.feed(pcm,24000):
            await send_audio(packet);state.packet(now())
    try:
        async with asyncio.timeout(10):
            await relay.connect()
            tasks.extend([relay.task(relay.output(delivered)),asyncio.ensure_future(relay.error)])
            peer.addTrack(relay.input_track)
            await peer.setLocalDescription(await peer.createOffer())
            offer={**scope,'client_id':config['device_id'],'session_id':ident,
                'conversation_id':config['conversation_id'],'sdp':peer.localDescription.sdp,
                'consent':True,'remember':False,'speak':True,'client_kind':'device',
                'personalization_mode':'guest','requested_voice':'marin','requested_model':'gpt-realtime-2.1-mini'}
            attempted=True
            response=await client.post(base,headers=headers,json=offer);response.raise_for_status();answer=response.json()
            if (answer.get('session_id')!=ident or answer.get('model')!='gpt-realtime-2.1-mini' or
                answer.get('voice')!='marin' or answer.get('configuration_confirmed') is not True):raise ValueError('hardware_b_configuration_unconfirmed')
            await peer.setRemoteDescription(RTCSessionDescription(sdp=answer['sdp'],type='answer'))
            if len(tracks)!=1 or tracks[0].kind!='audio':raise ValueError('hardware_b_audio_track_missing')
            tasks.append(relay.task(relay.microphone(GatedCapture(capture,state),wait_for_transport=True)))
            await relay.input_track.started.wait()
            await command('followup');state.listen()
            await send({'type':'gobot_media_ready'})

        async def media():
            nonlocal last_pcm
            resampler=av.AudioResampler(format='s16',layout='mono',rate=24000)
            while True:
                frame=await tracks[0].recv()
                for pcm in resampler.resample(frame):
                    raw=pcm.to_ndarray().astype('<i2').tobytes()
                    audible=np.max(np.abs(np.frombuffer(raw,'<i2').astype(np.int32)))>=8
                    if audible:
                        last_pcm=now()
                        if not state.response_id:await asyncio.wait_for(response_ready.wait(),.5)
                        if state.state=='Thinking':
                            state.state='Speaking';await send({'type':'tts','state':'start'})
                    if state.state=='Speaking' and now()-last_pcm<.3:await relay.send_speaker(raw)

        async def events():
            nonlocal flushed,started_ack,drain_started
            from spotpear_scene import project_scene
            serial=0
            async with client.stream('GET',f'{base}/{ident}/events',headers=headers,params=scope) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith('data: '):continue
                    event=json.loads(line[6:])
                    if event.get('session_id')!=ident:raise ValueError('unexpected_hardware_b_session')
                    if event['serial']<=serial:continue
                    serial=event['serial'];kind,data=event['type'],event['data']
                    if kind=='audio_diagnostic' and data.get('stage')=='server_audio_committed':state.commit()
                    elif kind=='processing' and data.get('response_id'):
                        state.response(data['response_id']);flushed=False;started_ack=False;drain_started=0.
                        response_ready.set()
                    elif kind=='generation_done':state.provider_done(data.get('response_id'),generation=True)
                    elif kind=='playback_buffer_stopped':state.provider_done(data.get('response_id'),drained=True)
                    elif kind=='visual_response':
                        with suppress(KeyError,ValueError):await send(project_scene(data['presentation']))
                    elif kind=='input_transcript':await send({'type':'stt','text':data.get('text','')[:512]})
                    elif kind=='error':raise ValueError('hardware_b_provider_error_no_retry')
                    elif kind=='closed':
                        await send({'type':'gobot_session_end','reason':data.get('reason')});return
            raise ValueError('hardware_b_control_lost_no_retry')

        async def drain():
            nonlocal flushed,started_ack,drain_started
            while True:
                stamp=getattr(capture,'activity_at',0.)
                state.activity(capture.playing,stamp)
                if state.client_started and not started_ack:
                    await command('playback_started',response_id=state.response_id);started_ack=True
                queues_empty=relay.output_queue.empty() and relay.speaker.queued_duration<=.001
                if state.generation_done and state.provider_drained and state.state=='Speaking':
                    if not drain_started:drain_started=now()
                    # RTP may outlive the sideband end marker. Wait for bounded tail,
                    # then flush the codec using one silence frame WITHOUT closing it.
                    if not flushed and queues_empty and now()-last_pcm>=.35:
                        for packet in encoder.feed(bytes(2880),24000):
                            await send_audio(packet);state.packet(now())
                        flushed=True
                    if flushed and state.drain(now(),queues_empty=queues_empty and now()-last_pcm>=.35):
                        await command('playback_stopped',response_id=state.response_id)
                        await command('followup') # Effective session.updated ACK before gate opens.
                        state.listen();response_ready.clear()
                        await send({'type':'tts','state':'stop'})
                    elif now()-drain_started>5:raise ValueError('hardware_b_playback_ack_missing')
                await asyncio.sleep(.02)

        terminal=asyncio.create_task(events())
        tasks.extend([terminal,asyncio.create_task(media()),asyncio.create_task(drain())])
        done,_=await asyncio.wait(tasks,return_when=asyncio.FIRST_COMPLETED)
        for task in done:task.result()
        if terminal not in done:raise ValueError('hardware_b_media_lost_no_retry')
    finally:
        state.stop()
        for task in tasks:task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        capture.stop();await peer.close();await relay.close()
        if attempted:
            with suppress(Exception):
                async with asyncio.timeout(8):await command('close',close_reason='user_stop')
