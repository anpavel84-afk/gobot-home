"""Opt-in HOST connection in the existing authenticated gateway. No paid sessions.
Raw Opus payload unchanged. JSON frame metadata carries epoch/sequence separately.
0.4.12 lacks HOST capabilities: reject honestly rather than changing its behavior.
"""
import asyncio,contextlib,json,time,uuid
from collections import deque
import av
from websockets.exceptions import ConnectionClosedOK
from host_wake_core import HostCore,StreamFault
CAPS={'version':1,'capture':'continuous','frame_sequence':True,'local_wake_enabled':False,'local_feedback':True,'playback_epoch':True}

class StreamOpus:
    def __init__(self):
        self.codec=av.CodecContext.create('opus','r')
        self.codec.extradata=b'OpusHead\x01\x01\x00\x00'+(16000).to_bytes(4,'little')+b'\x00\x00\x00'
        self.codec.open();self.resampler=av.AudioResampler(format='s16',layout='mono',rate=16000)
        self.closed=False;self.packets=0;self.samples=0
    def feed(self,packet):
        if self.closed or not 0<len(packet)<=4096:raise StreamFault('encoded_packet_limit')
        frames=self.codec.decode(av.Packet(packet));out=bytearray()
        if not frames or sum(f.samples*16000//f.sample_rate for f in frames)!=960:raise StreamFault('opus_duration_mismatch')
        for decoded in frames:
            for frame in self.resampler.resample(decoded):out.extend(frame.to_ndarray().astype('<i2',copy=False).tobytes())
        if not 0<len(out)<=1920:raise StreamFault('resampler_frame_limit')
        self.packets+=1;self.samples+=len(out)//2;return bytes(out)
    def close(self):
        # Never flush delayed old samples into the next transport epoch.
        self.closed=True;self.codec=None;self.resampler=None

class HostConnection:
    def __init__(self,detector_factory,*,clock=time.monotonic,max_queue_frames=4,max_queue_age=.25,allow_free_fixture=False):
        if not 1<=max_queue_frames<=8 or not .06<=max_queue_age<=.5:raise ValueError('invalid_transport_bounds')
        self.detector_factory=detector_factory;self.clock=clock;self.queue_limit=max_queue_frames;self.max_age=max_queue_age
        self.allow_free_fixture=allow_free_fixture is True
        self.fixture_requested=False;self.fixture_playback_id=None;self.fixture_playback_started=False
        self.fixture_output_finished=False;self.output_task=None
        self.stats={'received_packets':0,'max_queue_age_ms':0.,'max_queue_frames':0,'provider_calls':0,'financial_reservations':0,'raw_audio_saved':False,'screen_latency_measured':False,
                    'downlink_packets':0,'free_fixture_requested':False,
                    'fixture_playback_started_ack':False,'fixture_playback_drained_ack':False}
        self.ack_delays_ms=deque(maxlen=128);self.pending_feedback={};self.last_core=None;self.inflight=None
    async def compute(self,fn,*args,**kwargs):
        task=asyncio.create_task(asyncio.to_thread(fn,*args,**kwargs));self.inflight=task
        try:return await asyncio.shield(task)
        finally:
            if task.done():self.inflight=None
    @staticmethod
    def parse(raw):
        if not isinstance(raw,str) or len(raw)>4096:raise StreamFault('invalid_control_size')
        try:data=json.loads(raw)
        except (ValueError,TypeError) as error:raise StreamFault('invalid_control_json') from error
        if not isinstance(data,dict):raise StreamFault('invalid_control')
        return data
    async def run(self,ws,hello_validator):
        epoch=uuid.uuid4().hex;session_id=str(uuid.uuid4());queue=asyncio.Queue(maxsize=self.queue_limit)
        send_lock=asyncio.Lock()
        core=decoder=None;tasks=[];clean_mute=False
        try:
            hello=self.parse(await asyncio.wait_for(ws.recv(),8))
            caps=hello.get('host_stream')
            valid_caps=isinstance(caps,dict) and set(caps)==set(CAPS) and all(type(caps[k]) is type(v) and caps[k]==v for k,v in CAPS.items())
            if not hello_validator(hello) or not valid_caps:raise StreamFault('host_capability_required')
            detector=await self.compute(self.detector_factory);core=self.last_core=HostCore(detector,epoch);decoder=StreamOpus()
            async def send(data):
                async with send_lock:
                    await asyncio.wait_for(ws.send(json.dumps({**data,'session_id':session_id,'epoch':epoch},ensure_ascii=False)),2)
            async def send_media_frame(metadata,packet):
                # Protect each JSON-position + raw Opus pair against interleaving
                # with unrelated screen, STOP or playback control frames.
                async with send_lock:
                    await asyncio.wait_for(ws.send(json.dumps({**metadata,'session_id':session_id,'epoch':epoch})),2)
                    await asyncio.wait_for(ws.send(packet),2)
            async def output_fixture():
                try:
                    from host_downlink import fixture_packets
                    packets=await asyncio.to_thread(fixture_packets)
                    playback_id=uuid.uuid4().hex
                    self.fixture_playback_id=playback_id
                    await send({'type':'gobot_host_output_start','playback_id':playback_id,'audio_kind':'fixture',
                                'output_epoch':core.output_epoch,'codec':'opus',
                                'sample_rate':24000,'frame_samples':1440,'packet_count':len(packets)})
                    for seq,packet in enumerate(packets):
                        if core.stop_pending or core.output_epoch != 0:raise StreamFault('output_epoch_invalidated')
                        await send_media_frame({'type':'gobot_host_output_frame','playback_id':playback_id,
                                                'output_epoch':core.output_epoch,'seq':seq,
                                                'sample_start':seq*1440,'sample_count':1440},packet)
                        self.stats['downlink_packets']+=1
                        if seq+1<len(packets):await asyncio.sleep(.06)
                    await send({'type':'gobot_host_output_end','playback_id':playback_id,
                                'output_epoch':core.output_epoch,'packet_count':len(packets)})
                    self.fixture_output_finished=True
                except asyncio.CancelledError:
                    raise
                except Exception:
                    self.stats['last_failure_code']='free_downlink_failed'
                    with contextlib.suppress(Exception):await ws.close(1011,'Free downlink failed')
            await send({'type':'hello','version':1,'transport':'websocket','audio_params':{'format':'opus','sample_rate':24000,'channels':1,'frame_duration':60}})
            await send({'type':'gobot_host_ready','protocol':1,'wake_location':'HOST','paid_session_opened':False,'preroll_ms':2000,'frame_samples':960})
            ack=self.parse(await asyncio.wait_for(ws.recv(),8))
            if ack.get('type')!='gobot_host_ready_ack' or ack.get('epoch')!=epoch or ack.get('session_id')!=session_id or ack.get('frame_samples')!=960:raise StreamFault('host_start_not_acknowledged')
            async def receive():
                pending=None
                while True:
                    raw=await asyncio.wait_for(ws.recv(),2);now=self.clock()
                    if isinstance(raw,bytes):
                        if pending is None or not 0<len(raw)<=4096:raise StreamFault('binary_without_position')
                        item=('audio',pending,raw,now);pending=None;self.stats['received_packets']+=1
                    else:
                        obj=self.parse(raw)
                        if obj.get('epoch')!=epoch or obj.get('session_id')!=session_id:raise StreamFault('stale_transport_epoch')
                        if pending is not None:raise StreamFault('missing_binary_packet')
                        kind=obj.get('type')
                        if kind=='gobot_host_frame':pending=obj;continue
                        if kind not in {'gobot_host_touch','gobot_host_ack','gobot_host_playback','gobot_host_finish','gobot_host_mute','gobot_host_fixture'}:raise StreamFault('unsupported_host_control')
                        item=('control',obj,None,now)
                    try:queue.put_nowait(item)
                    except asyncio.QueueFull as error:raise StreamFault('host_queue_overflow') from error
                    self.stats['max_queue_frames']=max(self.stats['max_queue_frames'],queue.qsize())
            async def feedback(event):
                ident=event.get('activation_id') or event.get('command_id')
                if len(self.pending_feedback)>=8:raise StreamFault('feedback_ack_missing')
                self.pending_feedback[ident]={'sent':self.clock(),'seen':set(),'expected':{'stopped'} if event['event']=='stop' else {'rendered','cue_started'}}
                # Device owns local cue playback. This is NOT a fabricated Brain reply.
                await send({'type':'gobot_host_event',**event,'feedback_id':ident,'local_cue':event['event']=='wake','conversation_admitted':False})
                if event['event']=='wake':
                    await send({'type':'custom','payload':{'namespace':'gobot.ui','version':2,'command':'presentation.show','type':'status_card','title':'Обращение услышано','text':'HOST · локальная проверка; разговор отдельно'}})
            async def consume():
                nonlocal clean_mute
                while True:
                    kind,obj,packet,received=await queue.get()
                    try:
                        age=self.clock()-received;self.stats['max_queue_age_ms']=max(self.stats['max_queue_age_ms'],age*1000)
                        if age<0 or age>self.max_age:raise StreamFault('host_queue_stale')
                        if kind=='audio':
                            core.validate_frame(obj);pcm=await self.compute(decoder.feed,packet)
                            events=await self.compute(core.feed,obj,pcm,received_monotonic_ns=int(received*1_000_000_000))
                            for event in events:await feedback(event)
                        elif obj['type']=='gobot_host_touch':
                            if obj.get('gesture')=='stop':event=core.stop()
                            elif obj.get('gesture')=='activate':event=core.activate('physical_touch')
                            else:raise StreamFault('invalid_touch_gesture')
                            if event and event['event']=='stop' and self.output_task and not self.output_task.done():
                                self.output_task.cancel()
                                await asyncio.gather(self.output_task,return_exceptions=True)
                            if event:await feedback(event)
                        elif obj['type']=='gobot_host_ack':
                            ident=obj.get('feedback_id')
                            if ident not in self.pending_feedback:raise StreamFault('stale_feedback_ack')
                            receipt=self.pending_feedback[ident];event=obj.get('event')
                            if event not in receipt['expected']:raise StreamFault('invalid_feedback_ack')
                            if event not in receipt['seen']:
                                receipt['seen'].add(event);self.ack_delays_ms.append((self.clock()-receipt['sent'])*1000)
                                if event=='stopped':core.stop_ack(ident,obj.get('output_epoch'))
                            if receipt['seen']==receipt['expected']:self.pending_feedback.pop(ident)
                        elif obj['type']=='gobot_host_fixture':
                            if (not self.allow_free_fixture or self.fixture_requested or
                                    set(obj)!={'type','session_id','epoch'} or
                                    core.active is not None or core.speaking or core.stop_pending or
                                    self.pending_feedback):
                                raise StreamFault('fixture_request_forbidden')
                            self.fixture_requested=True
                            self.stats['free_fixture_requested']=True
                            self.output_task=asyncio.create_task(output_fixture())
                        elif obj['type']=='gobot_host_playback':
                            # Verify the origin and output ordering BEFORE touching
                            # the single-owner playback state.
                            if self.fixture_playback_id is not None:
                                if obj.get('playback_id')!=self.fixture_playback_id:
                                    raise StreamFault('stale_playback_id')
                                if obj.get('playing') is True:
                                    if self.fixture_playback_started or self.fixture_output_finished and self.stats['fixture_playback_drained_ack']:
                                        raise StreamFault('duplicate_playback_started')
                                elif obj.get('playing') is False:
                                    if not self.fixture_playback_started or not self.fixture_output_finished or self.stats['fixture_playback_drained_ack']:
                                        raise StreamFault('playback_drained_unconfirmed')
                                else:
                                    raise StreamFault('invalid_playback_state')
                            else:
                                raise StreamFault('unknown_playback_id')
                            core.playback(obj.get('playing'),obj.get('output_epoch'))
                            if obj['playing']:
                                self.fixture_playback_started=True
                                self.stats['fixture_playback_started_ack']=True
                            else:
                                self.stats['fixture_playback_drained_ack']=True
                        elif obj['type']=='gobot_host_finish':
                            utterance=core.finish_input()
                            if utterance:utterance.clear()
                            await send({'type':'gobot_host_idle','reason':'free_acceptance_only','paid_session_opened':False})
                        elif obj['type']=='gobot_host_mute':
                            if obj.get('muted') is not True:raise StreamFault('reconnect_required_to_unmute')
                            clean_mute=True
                            self.stats['clean_mute']=True
                            await ws.close(1000,'Host microphone muted');return
                    finally:queue.task_done()
            tasks=[asyncio.create_task(receive()),asyncio.create_task(consume())]
            done,_=await asyncio.wait(tasks,return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                try:task.result()
                except ConnectionClosedOK:
                    if not clean_mute:raise
        except asyncio.CancelledError:raise
        except Exception as error:
            self.stats['last_failure_kind']=type(error).__name__
            self.stats['last_failure_code']=str(error) if isinstance(error,StreamFault) else 'detector_or_transport_failed'
            with contextlib.suppress(Exception):await ws.close(1008,'HOST stream unavailable')
        finally:
            if self.output_task:
                if not self.output_task.done():self.output_task.cancel()
                await asyncio.gather(self.output_task,return_exceptions=True)
                self.output_task=None
            for task in tasks:task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
            # Cancellation of the waiter does not cancel native inference. Join it
            # before zeroing state; never race old inference against a new epoch.
            if self.inflight:
                with contextlib.suppress(Exception):await asyncio.shield(self.inflight)
                self.inflight=None
            if core:core.close()
            if decoder:decoder.close()
            while not queue.empty():queue.get_nowait();queue.task_done()
            self.pending_feedback.clear()
