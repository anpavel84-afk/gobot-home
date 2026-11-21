"""Issue #4: bounded local HOST transport state, independent of paid admission.
No network, disk, recording, training or provider dependencies in this module.
"""
from __future__ import annotations
from collections import deque
from dataclasses import dataclass,field
import time,uuid
from host_wake_contract import AudioChunk, WakeEvent
RATE=16000
FRAME_SAMPLES=960

class StreamFault(ValueError):pass

@dataclass(frozen=True)
class Detection:
    kind:str

@dataclass
class AudioBlock:
    start:int
    pcm:bytearray=field(repr=False)
    @property
    def end(self):return self.start+len(self.pcm)//2
    def clear(self):self.pcm[:]=bytes(len(self.pcm));self.pcm.clear()

class Ring:
    """Two-second history is not a deliberate two-second processing delay."""
    def __init__(self,capacity=32000):
        if not 1<=capacity<=48000:raise ValueError('invalid_preroll_capacity')
        self.capacity=capacity;self.blocks=deque();self.size=0
    def append(self,start,pcm):
        if not pcm or len(pcm)%2:raise StreamFault('invalid_pcm')
        if self.blocks and self.blocks[-1].end!=start:raise StreamFault('pcm_discontinuity')
        self.blocks.append(AudioBlock(start,bytearray(pcm)));self.size+=len(pcm)//2
        while self.size>self.capacity:
            first=self.blocks[0];trim=min(self.size-self.capacity,len(first.pcm)//2)
            first.pcm[:trim*2]=bytes(trim*2);del first.pcm[:trim*2]
            first.start+=trim;self.size-=trim
            if not first.pcm:self.blocks.popleft()
    def snapshot(self):return (self.blocks[0].start,b''.join(bytes(b.pcm) for b in self.blocks)) if self.blocks else (0,b'')
    def clear(self):
        for b in self.blocks:b.clear()
        self.blocks.clear();self.size=0

@dataclass
class ActiveInput:
    id:str
    source:str
    start:int
    cursor:int
    pcm:bytearray=field(repr=False)
    truncated:bool=False
    def clear(self):self.pcm[:]=bytes(len(self.pcm));self.pcm.clear()

class HostCore:
    def __init__(self,detector,epoch,*,max_input_seconds=15,allowed_wake_phrases=None):
        if not 1<=max_input_seconds<=30:raise ValueError('invalid_input_limit')
        self.detector=detector;self.epoch=epoch;self.history=Ring()
        self.allowed_wake_phrases=frozenset(allowed_wake_phrases) if allowed_wake_phrases is not None else None
        self.sample_cursor=0;self.expected_seq=0;self.active=None;self.speaking=False
        self.output_epoch=0;self.stop_pending=None;self.closed=False
        self.last_wake_end_sample_index=-1
        self.local_reply_pending=False
        self.max_input_samples=max_input_seconds*RATE
        self.counts={'frames':0,'activations':0,'stops':0,'duplicate_activations':0,'truncated_inputs':0}
    def validate_frame(self,meta):
        if self.closed:raise StreamFault('closed_stream')
        if meta.get('epoch')!=self.epoch:raise StreamFault('stale_transport_epoch')
        seq,start,count=(meta.get(k) for k in ('seq','sample_start','sample_count'))
        if any(type(v) is not int for v in (seq,start,count)):raise StreamFault('invalid_frame_position')
        if seq!=self.expected_seq or start!=seq*FRAME_SAMPLES or count!=FRAME_SAMPLES:raise StreamFault('source_discontinuity')
    def activate(self,source):
        if self.closed or self.speaking or self.stop_pending or self.local_reply_pending:return None
        if self.active:self.counts['duplicate_activations']+=1;return None
        if source not in ('host_wake','physical_touch'):raise StreamFault('invalid_activation_source')
        start,prefix=self.history.snapshot()
        self.active=ActiveInput(uuid.uuid4().hex,source,start,start+len(prefix)//2,bytearray(prefix))
        self.counts['activations']+=1
        return {'event':'wake','activation_id':self.active.id,'source':source,'prefix_start':start,'prefix_end':self.active.cursor,'paid_session_opened':False}
    def stop(self):
        if self.stop_pending or (not self.speaking and self.active is None and not self.local_reply_pending):return None
        old=self.output_epoch;self.output_epoch+=1
        if self.active:self.active.clear();self.active=None
        self.stop_pending=uuid.uuid4().hex;self.speaking=False
        self.local_reply_pending=False;self.counts['stops']+=1
        return {'event':'stop','command_id':self.stop_pending,'invalidated_output_epoch':old,'output_epoch':self.output_epoch,'provider_close_confirmed':False}
    def stop_ack(self,command_id,output_epoch):
        if not self.stop_pending or command_id!=self.stop_pending or type(output_epoch) is not int or output_epoch!=self.output_epoch:raise StreamFault('stale_stop_ack')
        self.stop_pending=None;self.detector.reset()
    def playback(self,playing,output_epoch):
        if type(playing) is not bool or type(output_epoch) is not int or output_epoch!=self.output_epoch:raise StreamFault('stale_playback_ack')
        if self.stop_pending:raise StreamFault('stop_not_acknowledged')
        self.speaking=playing
        if playing and self.active:self.active.clear();self.active=None
        if not playing:self.detector.reset()
    def finish_input(self):
        result=self.active;self.active=None;self.detector.reset();return result
    def feed(self,meta,pcm,*,received_monotonic_ns=None):
        self.validate_frame(meta)
        if not pcm or len(pcm)%2 or len(pcm)>FRAME_SAMPLES*2:raise StreamFault('decoded_frame_size')
        start=self.sample_cursor;end=start+len(pcm)//2
        self.history.append(start,pcm);self.sample_cursor=end;self.expected_seq+=1;self.counts['frames']+=1
        if self.active:
            if start!=self.active.cursor:raise StreamFault('active_input_discontinuity')
            if end-self.active.start>self.max_input_samples:
                self.active.truncated=True;self.active.clear();self.active=None;self.counts['truncated_inputs']+=1
                raise StreamFault('utterance_limit_truncated')
            self.active.pcm.extend(pcm);self.active.cursor=end
        # Feed canonical PCM BEFORE any conversation mask. HOST-B never sees Opus.
        if callable(getattr(self.detector,'feed_chunk',None)):
            stamp=time.monotonic_ns() if received_monotonic_ns is None else received_monotonic_ns
            event=self.detector.feed_chunk(AudioChunk(bytes(pcm),self.epoch,start,stamp))
        else:
            # Existing legacy detectors remain available until HOST-B is accepted.
            event=self.detector.feed(pcm,speaking=self.speaking)
        if not event:return []
        if isinstance(event,WakeEvent):
            if self.allowed_wake_phrases is not None and event.phrase_id not in self.allowed_wake_phrases:
                raise StreamFault("unapproved_wake_phrase")
            if self.active is not None or self.speaking or self.local_reply_pending or self.stop_pending:
                return []
            if (event.stream_epoch!=self.epoch or
                    event.end_sample_index>self.sample_cursor or
                    event.end_sample_index<=self.last_wake_end_sample_index or
                    event.end_sample_index<max(0,self.sample_cursor-2*RATE)):
                raise StreamFault('stale_or_replayed_wake_event')
            self.last_wake_end_sample_index=event.end_sample_index
            result=self.activate('host_wake')
        elif isinstance(event,Detection):
            if event.kind=='stop':result=self.stop() if self.speaking else None
            elif event.kind=='wake':result=self.activate('host_wake')
            else:raise StreamFault('unknown_detector_event')
        else:raise StreamFault('invalid_detector_event')
        return [result] if result else []
    def close(self):
        if self.active:self.active.clear();self.active=None
        self.history.clear();self.detector.reset();self.closed=True
        self.speaking=False;self.stop_pending=None;self.local_reply_pending=False
