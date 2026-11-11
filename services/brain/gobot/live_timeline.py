"""Timestamped conversation evidence. Delta grouping never grants authorization."""
import re
from dataclasses import dataclass
from hashlib import sha256

@dataclass(frozen=True)
class Segment:
    id:str
    role:str
    start:int
    end:int
    text:str

@dataclass(frozen=True)
class DelegationContext:
    delegation_id:str
    operation_id:str
    offset_ms:int
    query:str
    interaction_id:str
    complete:bool

class ConversationTimeline:
    def __init__(self):self.seen=set();self.segments=[];self.delegations={}
    def add(self,event):
        ident=event.get('event_id');kind=event.get('type')
        if not isinstance(ident,str) or not ident or ident in self.seen:return False
        if kind not in {'session.input_transcript.delta','session.output_transcript.delta'}:return False
        start=event.get('start_ms');end=event.get('end_ms');text=event.get('delta')
        if type(start) is not int or type(end) is not int or not 0<=start<=end or not isinstance(text,str) or not text or len(text)>8000:return False
        self.seen.add(ident)
        self.segments.append(Segment(ident,'user' if kind=='session.input_transcript.delta' else 'assistant',start,end,text))
        self.segments.sort(key=lambda s:(s.start,s.end,s.id));self.segments=self.segments[-256:]
        if len(self.seen)>2048:self.seen={s.id for s in self.segments}
        return True
    def context(self,delegation_id,offset):
        # Use provider acoustic timestamps, never the interval between network packets.
        inputs=[s for s in self.segments if s.role=='user' and s.start<=offset+500 and s.end>=offset-30000]
        if not inputs:return None
        chunks=[]
        for segment in reversed(inputs):
            if chunks and chunks[-1].start-segment.end>1200:break
            chunks.append(segment)
        chunks.reverse();query=''.join(s.text for s in chunks).strip()[:8000]
        interaction='speech-'+str(chunks[0].start)
        complete=bool(query and chunks[-1].end>=offset-1500)
        op=sha256((interaction+':'+str(offset)).encode()).hexdigest()[:32]
        return DelegationContext(delegation_id,op,offset,query,interaction,complete)
    def output_since(self,at):return ''.join(s.text for s in self.segments if s.role=='assistant' and s.end>=at)
    def clear(self):self.segments.clear();self.seen.clear();self.delegations.clear()
