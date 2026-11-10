"""Local activation gate. No cloud provider or continuous transcription dependency."""
import time
import re

def strip_activation(text):return re.sub(r'^\s*го[\s-]?бот(?:\s*[,!:—-]\s*|\s+|$)','',text,count=1,flags=re.I).strip()

class WakeWordActivationService:
    sample_rate=16000
    def __init__(self,detector=None,*,verified_russian_model=False,clock=time.monotonic):
        self.detector=detector if verified_russian_model else None
        self.clock=clock;self.buffer=bytearray();self.limit=self.sample_rate*2*2
        self.cooldown_until=0;self.enabled=False
    def status(self):return {'configured':self.detector is not None,'experimental':True,'runtime':'local host adapter',
        'keyword':'ГоБот','russian_pronunciation_verified':False,'buffer_seconds_limit':2,
        'external_calls_in_standby':0,'reason':None if self.detector else 'No installed and verified Russian GoBot keyword model'}
    def enable(self):
        if self.detector is None:raise RuntimeError('wake_word_not_configured')
        self.enabled=True
    def disable(self):self.enabled=False;self.buffer.clear()
    def feed(self,pcm,*,tts_playing=False):
        if not self.enabled or self.detector is None:return None
        now=self.clock()
        if tts_playing:self.buffer.clear();self.cooldown_until=now+.8;return None
        if now<self.cooldown_until:return None
        if len(pcm)>16000 or len(pcm)%2:raise ValueError('Bounded 16 kHz mono PCM chunks required')
        self.buffer.extend(pcm)
        if len(self.buffer)>self.limit:del self.buffer[:-self.limit]
        if not self.detector.feed(pcm):return None
        segment=bytes(self.buffer);self.buffer.clear();self.cooldown_until=now+2
        return {'activation':'gobot','preroll_pcm':segment,'requires_question_vad':True}
