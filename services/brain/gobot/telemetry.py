"""Bounded content-free traces. Clock domains are never subtracted from each other."""
import contextvars,hashlib,json,math,re,sqlite3,time
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

CURRENT=contextvars.ContextVar('gobot_trace',default=None)
ROOT=Path(__file__).resolve().parents[3]
META={'route','model','stt_mode','audio_seconds','input_bytes','context_tokens','concurrency','cache_hit','cold','voice','transport','code','profile_epoch','entity_revision','audio_role','provider','provider_session','utterance_id','request_id','turn_id','conversation_id','count_kind'}

@lru_cache(maxsize=4)
def _fingerprint(entries):
    return hashlib.sha256(b''.join(Path(path).read_bytes() for path,mtime in entries)).hexdigest()[:20]

@lru_cache(maxsize=1)
def code_commit():
    try:
        value=(ROOT/'.git/refs/heads/master').read_text().strip()
        return value if re.fullmatch('[a-f0-9]{40}',value) else 'unknown'
    except OSError:return 'unknown'

@lru_cache(maxsize=1)
def fingerprint():
    paths=[p for directory in [ROOT/'services/brain/gobot',ROOT/'services/phone/dist'] for p in directory.glob('*') if p.suffix in {'.py','.js'}]
    paths+=list((ROOT/'services/brain').glob('*.json'))
    return _fingerprint(tuple((str(p),p.stat().st_mtime_ns) for p in sorted(paths)))

class Trace:
    def __init__(self,ident,domain='brain',clock=time.perf_counter):
        self.id=ident;self.domain=domain;self.clock=clock;self.start=clock();self.events=[];self.metadata={}
    def mark(self,name,**metadata):
        if len(self.events)<256 and not any(e["name"]==name for e in self.events):self.events.append({'name':name,'ms':round((self.clock()-self.start)*1000,3),'metadata':{k:v for k,v in metadata.items() if k in META and (v is None or isinstance(v,(str,bool,int,float)))}})
        self.metadata.update({k:v for k,v in metadata.items() if k in META and (v is None or isinstance(v,(str,bool,int,float)))})
    def snapshot(self):return {'trace_id':self.id,'clock_domain':self.domain,'events':list(self.events),'metadata':dict(self.metadata),'code_config_fingerprint':fingerprint(),'code_commit':code_commit(),
        'unknown_stages':['provider_internal_inference','stt_tls_handshake','physical_acoustic_output'],'contains_content':False}

def mark(name,**metadata):
    trace=CURRENT.get()
    if trace:trace.mark(name,**metadata)

@contextmanager
def scope(trace):
    token=CURRENT.set(trace)
    try:yield trace
    finally:CURRENT.reset(token)

class Traces:
    def __init__(self,root):
        # Pin the running build, not files subsequently edited on disk.
        fingerprint();code_commit()
        self.db=Path(root)/'telemetry.sqlite';self.live={};self.db.parent.mkdir(parents=True,exist_ok=True)
        with sqlite3.connect(self.db) as c:c.execute('CREATE TABLE IF NOT EXISTS traces(owner TEXT,id TEXT,domain TEXT,data TEXT,created REAL,PRIMARY KEY(owner,id,domain))')
    def get(self,owner,ident):
        key=(owner,ident)
        if key not in self.live:
            if len(self.live)>=128:self.live.pop(next(iter(self.live)))
            self.live[key]=Trace(ident)
        return self.live[key]
    def save(self,owner,trace):
        data=trace.snapshot() if isinstance(trace,Trace) else trace
        with sqlite3.connect(self.db) as c:
            if data['clock_domain']=='client_monotonic':
                old=c.execute('SELECT data FROM traces WHERE owner=? AND id=? AND domain=?',(owner,data['trace_id'],data['clock_domain'])).fetchone()
                if old and json.loads(old[0]).get('revision',0)>data.get('revision',0):return
            c.execute('INSERT OR REPLACE INTO traces VALUES(?,?,?,?,?)',(owner,data['trace_id'],data['clock_domain'],json.dumps(data),time.time()))
            c.execute('DELETE FROM traces WHERE rowid NOT IN (SELECT rowid FROM traces ORDER BY created DESC LIMIT 2000)')
    def read(self,owner,ident):
        with sqlite3.connect(self.db) as c:return [json.loads(r[0]) for r in c.execute('SELECT data FROM traces WHERE owner=? AND id=?',(owner,ident))]

def client_trace(data):
    """Accept only named numeric offsets; never arbitrary log text or audio."""
    allowed={'input_closed','encoding_start','encoding_end','upload_start','stt_final_received','chat_submit','first_text','first_audio_received','decode_complete','scheduled','first_answer_playback','feedback_rendered','earcon_started','filler_started','filler_preempted','opening_offered','opening_decoded','opening_completed','opening_preempted','opening_skipped','opening_failed','followup_opened','visual_decoded','visual_presented','cancelled','error','playback_complete'}
    if not isinstance(data,dict) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,100}',str(data.get('trace_id',''))):raise ValueError('invalid_trace')
    seconds=data.get('audio_seconds');mode=data.get('stt_mode','text')
    if seconds is not None and (isinstance(seconds,bool) or not isinstance(seconds,(int,float)) or not math.isfinite(seconds) or not 0<=seconds<=61):raise ValueError('invalid_audio_duration')
    if mode not in {'text','file','live'}:raise ValueError('invalid_stt_mode')
    revision=data.get('revision',0)
    if not isinstance(revision,int) or isinstance(revision,bool) or not 0<=revision<=1000:raise ValueError('invalid_trace_revision')
    events=data.get('events',[])
    if not isinstance(events,list) or len(events)>64:raise ValueError('invalid_trace')
    clean=[]
    for row in events:
        if not isinstance(row,dict) or row.get('name') not in allowed:raise ValueError('invalid_trace_event')
        value=row.get('ms')
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not 0<=value<=600000:raise ValueError('invalid_trace_time')
        clean.append({'name':row['name'],'ms':value})
        code=row.get('code')
        if code is not None:
            if code not in {'settings','stale_turn','http','size','decode','web_audio','cancelled','timeout','answer_ready','complete','preempted'}:raise ValueError('invalid_trace_code')
            clean[-1]['code']=code
    return {'trace_id':data['trace_id'],'clock_domain':'client_monotonic','revision':revision,'audio_seconds':seconds,'stt_mode':mode,'events':clean,'source':'untrusted_client_estimated_output_not_acoustic_proof','contains_content':False}
