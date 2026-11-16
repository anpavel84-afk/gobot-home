"""Temporary scoped story jobs and actual-client ACKs; no hidden paid prefetch."""
import io,math,re,time,wave
from dataclasses import dataclass,field
from uuid import uuid4

FIXTURE_TITLE='Тестовый рассказ: мятный фонарь'
FIXTURE_TEXT=('В маленькой мастерской жил фонарь по имени Мятный. Каждый вечер он освещал рабочий стол, пока мастер чинил часы.\n\n'
 'Однажды часы остановились. Фонарь посветил под стол, и мастер увидел потерявшуюся пружинку. Они вернули её на место.\n\n'
 'Когда часы снова пошли, фонарь мигнул. Иногда помочь — значит просто осветить нужное место.')

@dataclass
class Story:
    scope:tuple
    title:str
    segments:list[str]
    fixture:bool=False
    id:str=field(default_factory=lambda:uuid4().hex)
    epoch:int=1
    state:str='paused'
    heard:dict=field(default_factory=dict)
    audio:dict=field(default_factory=dict)
    durations:dict=field(default_factory=dict)
    attempts:set=field(default_factory=set)
    started:set=field(default_factory=set)
    expires:float=field(default_factory=lambda:time.monotonic()+1800)

    def public(self):
        return {'id':self.id,'epoch':self.epoch,'title':self.title,'fixture':self.fixture,'state':self.state,
            'segments':[{'id':str(i),'text':text} for i,text in enumerate(self.segments)],'heard':self.heard,
            'synthetic_audio_not_speech':self.fixture,'resume_precision':'last_confirmed_segment'}

class Stories:
    def __init__(self):self.jobs={}
    def create(self,scope,text='',title='',fixture=False):
        self.jobs={k:v for k,v in self.jobs.items() if v.expires>time.monotonic()}
        if len(self.jobs)>=32:raise ValueError('story_capacity')
        if fixture:text=FIXTURE_TEXT;title=FIXTURE_TITLE
        if not 1<=len(text)<=4000:raise ValueError('story_text_limit')
        parts=[]
        for paragraph in re.split(r'\n\s*\n',text):
            while paragraph:
                stop=min(450,len(paragraph));cut=paragraph.rfind(' ',0,stop) if stop<len(paragraph) else stop
                cut=cut if cut>0 else stop;parts.append(paragraph[:cut].strip());paragraph=paragraph[cut:].strip()
        if len(parts)>12:raise ValueError('story_segment_limit')
        job=Story(tuple(scope),title[:80] or 'Ваш текст',parts,fixture)
        self.jobs[job.id]=job;return job
    def owned(self,ident,scope):
        job=self.jobs.get(ident)
        if not job or job.scope!=tuple(scope) or job.expires<=time.monotonic():raise PermissionError('story_not_owned_or_expired')
        return job
    @staticmethod
    def fixture_audio(job,index):
        if not job.fixture:raise ValueError('not_fixture_story')
        rate=24000;duration=1.2;raw=bytearray()
        for n in range(int(rate*duration)):
            value=int(1200*math.sin(2*math.pi*(330+index*110)*n/rate)*min(1,n/240,(rate*duration-n)/240))
            raw.extend(value.to_bytes(2,'little',signed=True))
        out=io.BytesIO()
        with wave.open(out,'wb') as f:f.setparams((1,2,rate,0,'NONE',''));f.writeframes(raw)
        job.durations[str(index)]=duration;return out.getvalue()
    @staticmethod
    def ack(job,ack):
        if ack.client_id!=job.scope[1] or ack.stream_id!=job.id or ack.epoch!=job.epoch or job.state=='stopped':raise ValueError('stale_or_foreign_playback_ack')
        if not ack.segment_id.isdecimal() or not 0<=int(ack.segment_id)<len(job.segments):raise ValueError('invalid_story_segment')
        duration=job.durations.get(ack.segment_id)
        if duration is None or ack.position_seconds>duration+.15:raise ValueError('unplayed_story_position')
        if ack.event=='started':job.started.add(ack.segment_id)
        elif ack.segment_id not in job.started:raise ValueError('story_playback_not_started')
        position=min(duration,ack.position_seconds)
        if position<job.heard.get(ack.segment_id,0):raise ValueError('out_of_order_playback_ack')
        job.heard[ack.segment_id]=position
        return {'accepted':True,'physical_audibility_verified':False}
    @staticmethod
    def heard_context(job):
        # Only completely played segments enter semantic context; partial audio is not text alignment.
        heard=[text for i,text in enumerate(job.segments) if str(i) in job.durations and job.heard.get(str(i),0)>=job.durations[str(i)]-.02]
        return {'title':job.title,'heard_segments':heard,'summary':' '.join(heard)[-1200:],
            'future_segments_included':False,'precision':'complete_segment'}
