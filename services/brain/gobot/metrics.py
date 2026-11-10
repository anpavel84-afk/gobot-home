import statistics,time
STAGES={'vad','stt','llm_first_token','tts_first_chunk','first_opus_playback','end_to_end'}
class StageMetrics:
    def __init__(self):self.started=time.perf_counter();self.values={}
    def mark(self,stage):
        if stage not in STAGES:raise ValueError('Unknown latency stage')
        self.values.setdefault(stage,(time.perf_counter()-self.started)*1000)
    def duration(self,stage,milliseconds):
        if stage not in STAGES or milliseconds<0:raise ValueError('Invalid stage sample')
        self.values[stage]=milliseconds
    def snapshot(self):return {stage:self.values.get(stage) for stage in sorted(STAGES)}
def percentiles(samples):
    values=sorted(samples)
    if not values:return {'n':0,'p50':None,'p95':None}
    return {'n':len(values),'p50':statistics.median(values),'p95':values[max(0,__import__('math').ceil(.95*len(values))-1)]}
