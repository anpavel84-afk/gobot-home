"""Hardware B state machine. Provider generation end is never a playback ACK."""
from dataclasses import dataclass

@dataclass
class HalfDuplex:
    state:str='Connecting'
    response_id:str|None=None
    generation_done:bool=False
    provider_drained:bool=False
    client_started:bool=False
    client_stopped_at:float|None=None
    last_packet_at:float=0.
    last_activity_at:float=0.
    echo_guard_seconds:float=.16 # 100 ms source queue + one 60 ms Opus frame.

    @property
    def input_open(self):return self.state=='Listening'

    def listen(self):
        if self.state not in {'Connecting','Drained'}:raise ValueError('hardware_playback_not_drained')
        self.state='Listening';self.response_id=None

    def commit(self):
        if self.state!='Listening':return False
        self.state='Thinking';return True

    def response(self,ident):
        if self.state in {'Stopped','Listening','Connecting'}:raise ValueError('response_outside_processing')
        if not ident or ident==self.response_id:return
        self.response_id=ident;self.state='Thinking';self.generation_done=False;self.provider_drained=False
        self.client_started=False;self.client_stopped_at=None;self.last_packet_at=0.

    def packet(self,now):
        if not self.response_id or self.state=='Stopped':raise ValueError('packet_outside_response')
        self.state='Speaking';self.last_packet_at=now;self.client_stopped_at=None

    def activity(self,playing,now):
        if now<=self.last_activity_at:return
        self.last_activity_at=now
        if not self.response_id or not self.last_packet_at or now<self.last_packet_at:return
        if playing:self.client_started=True;self.client_stopped_at=None
        elif self.client_started and self.client_stopped_at is None:self.client_stopped_at=now

    def provider_done(self,ident,*,generation=False,drained=False):
        if ident!=self.response_id:return
        self.generation_done|=generation;self.provider_drained|=drained

    def drain(self,now,*,queues_empty):
        if (self.state!='Speaking' or not self.generation_done or not self.provider_drained or
            not self.client_started or self.client_stopped_at is None or not queues_empty or
            now-max(self.last_packet_at,self.client_stopped_at)<self.echo_guard_seconds):return False
        self.state='Drained';return True

    def stop(self):self.state='Stopped'
