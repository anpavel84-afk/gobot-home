"""Opt-in HOST connection in the existing authenticated gateway. No paid sessions.
Raw Opus payload unchanged. JSON frame metadata carries epoch/sequence separately.
0.4.12 lacks HOST capabilities: reject honestly rather than changing its behavior.
"""
import asyncio,contextlib,json,time,uuid,math,struct,statistics
from collections import deque
import av
from websockets.exceptions import ConnectionClosedOK,ConnectionClosedError
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
        # PyAV/FFmpeg removes Opus decoder pre-skip (16 samples at 16 kHz)
        # from the FIRST packet. The physical producer's seq*960 index still
        # includes these samples: restore timing with silence, not old audio.
        if self.packets==0 and len(out)==1888:
            out[:0]=bytes(32)
        if len(out)!=1920:raise StreamFault('resampler_frame_timing_mismatch')
        self.packets+=1;self.samples+=960;return bytes(out)
    def close(self):
        # Never flush delayed old samples into the next transport epoch.
        self.closed=True;self.codec=None;self.resampler=None

class HostConnection:
    def __init__(self,detector_factory,*,clock=time.monotonic,max_queue_frames=4,max_queue_age=.25,allow_free_fixture=False,input_level_stats=False,fixture_packets_factory=None,local_command_responder=None,monika_trial=False,streaming_turn_factory=None):
        if not 1<=max_queue_frames<=8 or not .06<=max_queue_age<=.5:raise ValueError('invalid_transport_bounds')
        self.detector_factory=detector_factory;self.clock=clock;self.queue_limit=max_queue_frames;self.max_age=max_queue_age
        self.allow_free_fixture=allow_free_fixture is True
        self.input_level_stats=input_level_stats is True
        if fixture_packets_factory is not None and not callable(fixture_packets_factory):
            raise TypeError("fixture_factory_must_be_callable")
        self.fixture_packets_factory=fixture_packets_factory
        if local_command_responder is not None and not callable(local_command_responder):
            raise TypeError("local_command_responder_must_be_callable")
        self.local_command_responder=local_command_responder
        self.monika_trial=monika_trial is True
        if streaming_turn_factory is not None and not callable(streaming_turn_factory):
            raise TypeError("streaming_turn_factory_must_be_callable")
        self.streaming_turn_factory=streaming_turn_factory
        self.activation_cursor=None;self.wake_blocked_until=0.0
        self.output_serial=0;self.cancelled_playbacks=deque(maxlen=8)
        self.local_job=None;self.local_inflight=None
        self.fixture_requested=False;self.fixture_playback_id=None;self.fixture_playback_started=False
        self.fixture_output_finished=False;self.output_task=None
        self.stats={'received_packets':0,'max_queue_age_ms':0.,'max_queue_frames':0,'provider_calls':0,'financial_reservations':0,'raw_audio_saved':False,'screen_latency_measured':False,
                    'downlink_packets':0,'free_fixture_requested':False,
                    'fixture_playback_started_ack':False,'fixture_playback_drained_ack':False}
        self.stats.update(pcm_frames=0,pcm_peak_abs=0,pcm_max_rms=0.,pcm_nonquiet_frames=0,last_input_seq=-1,
                          pcm_total_samples=0,pcm_clipped_samples=0,pcm_rms_min=None,pcm_abs_dc_max=0.)
        self.queue_age_samples_ms=deque(maxlen=40000)
        self.stats.update(queue_age_sample_count=0,received_span_s=0.0,session_first_frame_recv_s=None,
                          session_last_frame_recv_s=None,abrupt_device_close=False,
                          local_command_jobs=0,local_command_recognized=0,
                          local_command_unrecognized=0,local_command_failures=0,
                          manual_touch_activations=0,manual_touch_stops=0,
                          wake_activations=0,screen_acks=0,cue_acks=0,
                          ignored_early_device_finishes=0,completed_replies=0)
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
        core=decoder=streaming_turn=None;tasks=[];clean_mute=False
        try:
            hello=self.parse(await asyncio.wait_for(ws.recv(),8))
            caps=hello.get('host_stream')
            valid_caps=isinstance(caps,dict) and set(caps)==set(CAPS) and all(type(caps[k]) is type(v) and caps[k]==v for k,v in CAPS.items())
            if not hello_validator(hello) or not valid_caps:raise StreamFault('host_capability_required')
            detector=await self.compute(self.detector_factory);core=self.last_core=HostCore(detector,epoch,allowed_wake_phrases={"monika"} if self.monika_trial else None);decoder=StreamOpus()
            if self.streaming_turn_factory is not None:
                if not self.monika_trial:
                    raise StreamFault("streaming_trial_requires_isolated_monika")
                streaming_turn=self.streaming_turn_factory()
            async def send(data):
                async with send_lock:
                    await asyncio.wait_for(ws.send(json.dumps({**data,'session_id':session_id,'epoch':epoch},ensure_ascii=False)),2)
            async def send_media_frame(metadata,packet):
                # Protect each JSON-position + raw Opus pair against interleaving
                # with unrelated screen, STOP or playback control frames.
                async with send_lock:
                    await asyncio.wait_for(ws.send(json.dumps({**metadata,'session_id':session_id,'epoch':epoch})),2)
                    await asyncio.wait_for(ws.send(packet),2)
            async def output_fixture(prebuilt_packets=None):
                generation=core.output_epoch
                try:
                    from host_downlink import fixture_packets
                    packets=(prebuilt_packets if prebuilt_packets is not None
                             else await asyncio.to_thread(self.fixture_packets_factory or fixture_packets))
                    if not 1<=len(packets)<=64 or any(not isinstance(p,bytes) or not 0<len(p)<=4096 for p in packets):
                        raise StreamFault("free_fixture_packetization_invalid")
                    if core.stop_pending or core.output_epoch!=generation:
                        raise StreamFault("output_epoch_invalidated_before_start")
                    playback_id=uuid.uuid4().hex
                    self.fixture_playback_id=playback_id
                    self.fixture_playback_started=False;self.fixture_output_finished=False
                    self.stats["fixture_playback_started_ack"]=False
                    self.stats["fixture_playback_drained_ack"]=False
                    await send({'type':'gobot_host_output_start','playback_id':playback_id,'audio_kind':'fixture',
                                'output_epoch':core.output_epoch,'codec':'opus',
                                'sample_rate':24000,'frame_samples':1440,'packet_count':len(packets)})
                    for seq,packet in enumerate(packets):
                        if core.stop_pending or core.output_epoch != generation:raise StreamFault('output_epoch_invalidated')
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
            async def process_local_command(utterance):
                generation=core.output_epoch
                # Existing HostCore alone creates the wake/touch ActiveInput.
                # This worker does not consume or block the continuous Opus queue.
                try:
                    if streaming_turn is not None and utterance.source=='host_wake':
                        # Cloud transcription was already open and receiving
                        # live 60ms frames while the owner was speaking.
                        packets=await streaming_turn.reply()
                    else:
                        pcm=bytes(utterance.pcm)
                        future=asyncio.create_task(asyncio.to_thread(self.local_command_responder,pcm))
                        self.local_inflight=future
                        packets=await asyncio.shield(future)
                        pcm=b''
                    if core.stop_pending or core.output_epoch!=generation or not core.local_reply_pending:
                        return  # Physical Stop invalidated all pending results.
                    if packets:
                        if (self.output_task is not None and not self.output_task.done()) or core.speaking:
                            raise StreamFault("local_command_reply_conflicts_with_output")
                        self.stats['local_command_recognized']+=1
                        self.output_task=asyncio.create_task(output_fixture(packets))
                        await self.output_task
                        # A device driver playback receipt, not output_end,
                        # releases core.local_reply_pending in consume().
                    else:
                        self.stats['local_command_unrecognized']+=1
                        core.local_reply_pending=False
                    if not core.stop_pending:
                        await send({'type':'gobot_host_idle','reason':'free_local_command',
                                    'paid_session_opened':False})
                except asyncio.CancelledError:
                    raise
                except Exception:
                    self.stats['local_command_failures']+=1
                    core.local_reply_pending=False
                    with contextlib.suppress(Exception):
                        await send({'type':'gobot_host_idle',
                                    'reason':'local_command_unavailable',
                                    'paid_session_opened':False})
                finally:
                    utterance.clear()
                    self.local_job=None

            async def finish_active_input():
                if core.active is None:return
                if streaming_turn is not None and core.active.source=='host_wake':
                    await streaming_turn.finish()
                utterance=core.finish_input()
                if (utterance and self.local_command_responder is not None
                        and self.local_job is None and not core.speaking
                        and not core.stop_pending):
                    core.local_reply_pending=True
                    self.stats['local_command_jobs']+=1
                    self.local_job=asyncio.create_task(process_local_command(utterance))
                else:
                    if utterance:utterance.clear()
                    await send({'type':'gobot_host_idle','reason':'free_acceptance_only',
                                'paid_session_opened':False})
                self.activation_cursor=None

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
                        if self.stats['session_first_frame_recv_s'] is None:
                            self.stats['session_first_frame_recv_s']=now
                        self.stats['session_last_frame_recv_s']=now
                        self.stats['received_span_s']=round(now-self.stats['session_first_frame_recv_s'],3)
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
                    self.activation_cursor=core.sample_cursor
                    if event.get('source')=='host_wake':self.stats['wake_activations']+=1
                    await send({'type':'custom','payload':{'namespace':'gobot.ui','version':2,'command':'presentation.show','type':'status_card','title':'Обращение услышано','text':'HOST · локальная проверка; разговор отдельно'}})
            async def consume():
                nonlocal clean_mute
                while True:
                    kind,obj,packet,received=await queue.get()
                    try:
                        age=self.clock()-received;self.stats['max_queue_age_ms']=max(self.stats['max_queue_age_ms'],age*1000)
                        self.queue_age_samples_ms.append(round(age*1000,4))
                        self.stats['queue_age_sample_count']+=1
                        if age<0 or age>self.max_age:raise StreamFault('host_queue_stale')
                        if kind=='audio':
                            core.validate_frame(obj);pcm=await self.compute(decoder.feed,packet)
                            if self.input_level_stats:
                                # Only numeric aggregate; PCM and transcripts never logged.
                                samples=struct.unpack('<'+str(len(pcm)//2)+'h',pcm)
                                peak=max(abs(v) for v in samples)
                                rms=math.sqrt(sum(v*v for v in samples)/len(samples))
                                self.stats['pcm_frames']+=1
                                self.stats['pcm_peak_abs']=max(self.stats['pcm_peak_abs'],peak)
                                self.stats['pcm_max_rms']=max(self.stats['pcm_max_rms'],round(rms,2))
                                self.stats['pcm_nonquiet_frames']+=int(rms>=100)
                                self.stats['pcm_total_samples']+=len(samples)
                                self.stats['pcm_clipped_samples']+=sum(abs(v)>=32700 for v in samples)
                                self.stats['pcm_rms_min']=round(min(rms,self.stats['pcm_rms_min']) if self.stats['pcm_rms_min'] is not None else rms,2)
                                self.stats['pcm_abs_dc_max']=max(self.stats['pcm_abs_dc_max'],round(abs(sum(samples)/len(samples)),2))
                                self.stats['last_input_seq']=obj['seq']
                            if self.monika_trial and hasattr(detector,'suppress_events'):
                                detector.suppress_events=bool(core.speaking or core.local_reply_pending or
                                                              core.stop_pending or self.clock()<self.wake_blocked_until or
                                                              (self.local_inflight is not None and not self.local_inflight.done()))
                            if streaming_turn is not None and streaming_turn.active:
                                # Source position BEFORE core.feed advances
                                # sample cursor; each frame is queued only once.
                                from host_wake_contract import AudioChunk
                                streaming_turn.offer(AudioChunk(
                                    bytes(pcm),epoch,core.sample_cursor,
                                    int(received*1_000_000_000)))
                            events=await self.compute(core.feed,obj,pcm,received_monotonic_ns=int(received*1_000_000_000))
                            for event in events:
                                if streaming_turn is not None and event.get('source')=='host_wake':
                                    await streaming_turn.on_wake(event)
                                await feedback(event)
                            if (self.monika_trial and core.active is not None and
                                    core.active.source=='host_wake' and self.activation_cursor is not None):
                                elapsed=core.sample_cursor-self.activation_cursor
                                endpoint=(getattr(detector,'endpoint_sample',-1)>=self.activation_cursor or
                                          bool(getattr(detector,'utterance_endpoint',False)))
                                if (endpoint and elapsed>=4800) or elapsed>=160000:
                                    await finish_active_input()
                        elif obj['type']=='gobot_host_touch':
                            if obj.get('gesture')=='stop':event=core.stop()
                            elif obj.get('gesture')=='activate':
                                event=(None if self.local_inflight is not None and not self.local_inflight.done()
                                       else core.activate('physical_touch'))
                            else:raise StreamFault('invalid_touch_gesture')
                            if event and event['event']=='stop':
                                if streaming_turn is not None:
                                    await streaming_turn.cancel()
                                if self.fixture_playback_id:self.cancelled_playbacks.append((self.fixture_playback_id,event['invalidated_output_epoch']))
                                self.activation_cursor=None
                                if self.local_job and not self.local_job.done():
                                    self.local_job.cancel()
                                    await asyncio.gather(self.local_job,return_exceptions=True)
                                if self.output_task and not self.output_task.done():
                                    self.output_task.cancel()
                                    await asyncio.gather(self.output_task,return_exceptions=True)
                            if event and obj.get('gesture')=='activate':
                                self.stats['manual_touch_activations']+=1
                            if event and obj.get('gesture')=='stop':
                                self.stats['manual_touch_stops']+=1
                            if event:await feedback(event)
                        elif obj['type']=='gobot_host_ack':
                            ident=obj.get('feedback_id')
                            if ident not in self.pending_feedback:raise StreamFault('stale_feedback_ack')
                            receipt=self.pending_feedback[ident];event=obj.get('event')
                            if event not in receipt['expected']:raise StreamFault('invalid_feedback_ack')
                            if event not in receipt['seen']:
                                receipt['seen'].add(event);self.ack_delays_ms.append((self.clock()-receipt['sent'])*1000)
                                if event=='stopped':core.stop_ack(ident,obj.get('output_epoch'))
                                if event=='rendered':self.stats['screen_acks']+=1
                                if event=='cue_started':self.stats['cue_acks']+=1
                            if receipt['seen']==receipt['expected']:self.pending_feedback.pop(ident)
                        elif obj['type']=='gobot_host_fixture':
                            if (not self.allow_free_fixture or self.fixture_requested or
                                    set(obj)!={'type','session_id','epoch'} or
                                    core.active is not None or core.speaking or core.stop_pending or
                                    core.local_reply_pending or self.pending_feedback):
                                raise StreamFault('fixture_request_forbidden')
                            self.fixture_requested=True
                            self.stats['free_fixture_requested']=True
                            self.output_task=asyncio.create_task(output_fixture())
                        elif obj['type']=='gobot_host_playback':
                            if (obj.get('playback_id'),obj.get('output_epoch')) in self.cancelled_playbacks:
                                continue
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
                                core.local_reply_pending=False
                                self.stats['fixture_playback_started_ack']=True
                            else:
                                self.stats['fixture_playback_drained_ack']=True
                                self.stats['completed_replies']+=1
                                self.wake_blocked_until=self.clock()+.4
                        elif obj['type']=='gobot_host_finish':
                            if (self.monika_trial and core.active is not None and
                                    core.active.source=='host_wake'):
                                # r3's local touch timer is not initialized by a remote wake.
                                # Keep the RAM capture alive until B's actual speech endpoint;
                                # early firmware finish must never cut the coarticulated question.
                                self.stats['ignored_early_device_finishes']+=1
                            else:
                                await finish_active_input()
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
            if isinstance(error,(ConnectionClosedError,ConnectionClosedOK)):
                # No gobot_host_mute / explicit application goodbye from the
                # current installed RC1 firmware. Do not claim clean close.
                self.stats['abrupt_device_close']=not clean_mute
                self.stats['last_failure_code']='device_websocket_closed_without_host_goodbye'
            else:
                self.stats['last_failure_code']=str(error) if isinstance(error,StreamFault) else 'detector_or_transport_failed'
            with contextlib.suppress(Exception):await ws.close(1008,'HOST stream unavailable')
        finally:
            if streaming_turn is not None:
                await streaming_turn.cancel()
            if self.local_job:
                if not self.local_job.done():self.local_job.cancel()
                await asyncio.gather(self.local_job,return_exceptions=True)
                self.local_job=None
            if self.local_inflight:
                # Native CPU inference may outlive task cancellation; join it
                # before any new epoch can reuse model state.
                with contextlib.suppress(Exception):
                    await asyncio.shield(self.local_inflight)
                self.local_inflight=None
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
            if self.queue_age_samples_ms:
                sample=sorted(self.queue_age_samples_ms)
                self.stats['queue_age_p50_ms']=round(statistics.median(sample),4)
                self.stats['queue_age_p95_ms']=round(sample[max(0,math.ceil(len(sample)*.95)-1)],4)
            if core:
                self.stats['core_processed_frames']=core.counts['frames']
                self.stats['core_touch_or_wake_activations']=core.counts['activations']
                self.stats['core_stop_events']=core.counts['stops']
                core.close()
            if decoder:decoder.close()
            while not queue.empty():queue.get_nowait();queue.task_done()
            self.pending_feedback.clear()
