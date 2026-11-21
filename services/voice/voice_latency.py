"""Issue #4 / L0: bounded, content-free monotonic evidence. No I/O or billing.
Clock domains NEVER subtract without an explicit validated calibration.
Device playback is instrumented evidence, not proof of audible/meaningful content.
"""
from __future__ import annotations
from dataclasses import dataclass
import math
import re
import time
import uuid

EVENTS=frozenset({
 'activation_accepted','capture_begin','mic_first_speech','mic_last_speech',
 'utterance_end_decided','gateway_first_frame','gateway_last_frame','relay_ready',
 'sdp_ready','provider_configuration_confirmed','provider_media_ready',
 'provider_speech_started','provider_speech_stopped','provider_audio_committed',
 'provider_response_created','provider_first_output_audio','relay_first_output_audio',
 'first_output_packet_sent','output_packet_received','playback_started','playback_drained',
 'output_write_enter','output_write_return','output_tasks_drained',
 'manual_speech_end','manual_meaningful_playback','wake_detected','listening_rendered',
 'input_gate_open','input_gate_closed','session_close_requested','local_resources_released'})
DEVICE_EVENTS=frozenset({'activation_accepted','capture_begin','mic_first_speech','mic_last_speech',
 'utterance_end_decided','output_packet_received','playback_started','playback_drained','listening_rendered',
 'output_write_enter','output_write_return','output_tasks_drained'})
KINDS=frozenset({'unknown','earcon','fixture','provider_reply','human_verified_reply'})
GAUGES=frozenset({'input_backlog_ms','relay_output_queue_frames','relay_speaker_queued_ms',
 'source_frame_age_ms','gateway_queue_age_ms','send_pacing_wait_ms'})
ID=re.compile(r'^[a-zA-Z0-9_-]{1,64}$')

@dataclass(frozen=True)
class Stamp:
    event:str
    domain:str
    milliseconds:float
    turn:int=0
    kind:str='unknown'
    evidence:str='instrumented'

class LatencyTrace:
    def __init__(self,*,trace_id=None,clock=time.monotonic,limit=256):
        self.trace_id=trace_id or uuid.uuid4().hex
        if not ID.fullmatch(self.trace_id) or not 16<=limit<=512:raise ValueError('invalid_latency_trace')
        self.clock=clock;self.limit=limit;self.origin=clock();self.turn=0
        self.stamps={};self.gauges={};self.overflow=0;self.invalid=0
        self.device_clock=None;self.device_sequences=set();self.device_highest=-1
        self.response_ids={};self.closed=False
    def response(self,ident):
        if not isinstance(ident,str) or not ID.fullmatch(ident):return self.turn
        if ident not in self.response_ids:
            if len(self.response_ids)>=32:raise ValueError('latency_turn_limit')
            self.response_ids[ident]=len(self.response_ids)
        self.turn=self.response_ids[ident];return self.turn
    def input_started(self):
        if len(self.response_ids)>=32:raise ValueError('latency_turn_limit')
        self.turn=len(self.response_ids)
        self.mark('provider_speech_started')
    def mark(self,event,*,domain='gateway',milliseconds=None,turn=None,kind='unknown',evidence='instrumented',last=False):
        if self.closed:return
        if domain!='gateway' and milliseconds is None:raise ValueError('explicit_remote_clock_required')
        turn=self.turn if turn is None else turn
        stamp=(self.clock()-self.origin)*1000 if milliseconds is None else milliseconds
        if event not in EVENTS or kind not in KINDS or domain not in {'gateway','device','manual_acoustic'} or type(turn) is not int or not 0<=turn<32:
            raise ValueError('invalid_latency_event')
        if isinstance(stamp,bool) or not isinstance(stamp,(int,float)) or not math.isfinite(stamp) or stamp<0:
            raise ValueError('invalid_latency_clock')
        if evidence not in {'instrumented','device_vad_estimate','manual_acoustic','fixture'}:raise ValueError('invalid_latency_evidence')
        key=(domain,turn,event,kind)
        if key in self.stamps and not last:return
        if key not in self.stamps and len(self.stamps)>=self.limit:self.overflow+=1;return
        self.stamps[key]=Stamp(event,domain,float(stamp),turn,kind,evidence)
    def gauge(self,name,value):
        if name not in GAUGES or isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<0:
            raise ValueError('invalid_latency_gauge')
        old=self.gauges.get(name,{'max':0.,'last':0.,'count':0})
        self.gauges[name]={'max':max(old['max'],float(value)),'last':float(value),'count':min(old['count']+1,10000000)}
    def device_event(self,obj,*,session_id):
        allowed={'type','session_id','trace_id','turn','clock_epoch','seq','device_us','event','audio_kind'}
        if not isinstance(obj,dict) or set(obj)!=allowed or obj['type']!='gobot_latency' or obj['trace_id']!=self.trace_id or obj['session_id']!=session_id:
            raise ValueError('invalid_device_latency_scope')
        if not isinstance(obj['clock_epoch'],str) or not ID.fullmatch(obj['clock_epoch']):raise ValueError('invalid_device_clock_epoch')
        if self.device_clock is None:self.device_clock=obj['clock_epoch']
        if self.device_clock!=obj['clock_epoch']:raise ValueError('changed_device_clock_epoch')
        seq=obj['seq'];us=obj['device_us']
        if type(seq) is not int or seq<0 or seq<=self.device_highest or type(us) is not int or not 0<=us<2**53:
            raise ValueError('stale_device_latency')
        if obj['event'] not in DEVICE_EVENTS or obj['audio_kind'] not in KINDS-{'human_verified_reply'}:raise ValueError('invalid_device_latency_stage')
        self.mark(obj['event'],domain='device',milliseconds=us/1000.,turn=obj['turn'],kind=obj['audio_kind'],
                  evidence='device_vad_estimate' if obj['event'] in {'mic_first_speech','mic_last_speech'} else 'instrumented',
                  last=obj['event']=='mic_last_speech')
        self.device_highest=seq
    def interval(self,start,end,*,domain,turn=0,start_kind='unknown',end_kind='unknown'):
        a=self.stamps.get((domain,turn,start,start_kind));b=self.stamps.get((domain,turn,end,end_kind))
        if not a or not b:return {'status':'NOT_MEASURED','reason':'missing_same_clock_landmarks'}
        if b.milliseconds<a.milliseconds:return {'status':'INVALID','reason':'landmark_order'}
        return {'status':'MEASURED','ms':round(b.milliseconds-a.milliseconds,3),
                'clock_domain':domain,'start_evidence':a.evidence,'end_evidence':b.evidence}
    def summary(self):
        turns=sorted({s.turn for s in self.stamps.values()})
        metrics={}
        for turn in turns:
            metrics[str(turn)]={
              'touch_to_capture_device':self.interval('activation_accepted','capture_begin',domain='device',turn=turn),
              'vad_end_to_provider_playback_device':self.interval('mic_last_speech','playback_started',domain='device',turn=turn,end_kind='provider_reply'),
              'device_vad_end_to_output_write_proxy':self.interval('mic_last_speech','output_write_enter',domain='device',turn=turn,end_kind='provider_reply'),
              'device_output_write_to_tasks_drained_proxy':self.interval('output_write_enter','output_tasks_drained',domain='device',turn=turn,start_kind='provider_reply',end_kind='provider_reply'),
              'speech_end_to_meaningful_audible_reply':self.interval('manual_speech_end','manual_meaningful_playback',domain='manual_acoustic',turn=turn,end_kind='human_verified_reply'),
              'gateway_commit_to_first_audio':self.interval('provider_audio_committed','provider_first_output_audio',domain='gateway',turn=turn,end_kind='provider_reply'),
              'gateway_first_audio_to_packet':self.interval('provider_first_output_audio','first_output_packet_sent',domain='gateway',turn=turn,start_kind='provider_reply',end_kind='provider_reply')}
        return {'schema':'gobot_latency_v1','trace_id':self.trace_id,'clock_alignment':'NONE_CROSS_CLOCK_SUBTRACTION_FORBIDDEN',
                'events':[{'stage':s.event,'clock':s.domain,'ms':round(s.milliseconds,3),'turn':s.turn,'audio_kind':s.kind,'evidence':s.evidence} for s in self.stamps.values()],
                'metrics':metrics,'gauges':self.gauges,'overflow':self.overflow,
                'physical_latency_accepted':False,'meaningful_audio_not_inferred_from_packet':True}


def mark(capture,event,**kw):
    trace=getattr(capture,'latency',None)
    if trace is not None:trace.mark(event,**kw)
