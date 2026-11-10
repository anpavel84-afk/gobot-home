"""Persistent, content-free admission and usage; silence is not assumed free."""
import hashlib,json,sqlite3,time
from pathlib import Path
from .realtime_contract import RealtimePolicy

class RealtimeBudget:
    def __init__(self,root):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        self.path=self.root/'usage.sqlite';self.policy_path=self.root/'policy.json'
        with self.connect() as c:
            c.execute('CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY,authorization TEXT,started REAL,responses INTEGER DEFAULT 0)')
            c.execute('CREATE TABLE IF NOT EXISTS usage(session TEXT,response TEXT,usage TEXT,PRIMARY KEY(session,response))')
            c.execute('CREATE TABLE IF NOT EXISTS cancelled(id TEXT PRIMARY KEY,scope TEXT)')
            c.execute('CREATE TABLE IF NOT EXISTS calls(id TEXT PRIMARY KEY,closed INTEGER DEFAULT 0)')
    def connect(self):return sqlite3.connect(self.path,timeout=5)
    def policy(self):
        if not self.policy_path.exists():return RealtimePolicy()
        return RealtimePolicy.model_validate_json(self.policy_path.read_text(encoding='utf-8'))
    @staticmethod
    def key(ident):return hashlib.sha256(ident.encode()).hexdigest()
    def reserve_session(self,ident,consent):
        p=self.policy()
        if not (p.enabled and p.authorization and p.expires_at>time.time() and consent):raise PermissionError('realtime_budget_or_consent_required')
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            if c.execute('SELECT 1 FROM cancelled WHERE id=?',(self.key(ident),)).fetchone():raise ValueError('realtime_session_cancelled')
            if c.execute('SELECT 1 FROM sessions WHERE id=?',(self.key(ident),)).fetchone():raise ValueError('realtime_session_already_attempted')
            count=c.execute('SELECT count(*) FROM sessions WHERE authorization=?',(p.authorization,)).fetchone()[0]
            if count>=p.max_sessions:raise PermissionError('realtime_session_budget_exhausted')
            c.execute('INSERT INTO sessions(id,authorization,started) VALUES(?,?,?)',(self.key(ident),p.authorization,time.time()))
        return p
    def cancel(self,ident,scope):
        digest=self.key(json.dumps(scope))
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT scope FROM cancelled WHERE id=?',(self.key(ident),)).fetchone()
            if row and row[0]!=digest:raise KeyError('realtime_session_not_found')
            c.execute('INSERT OR IGNORE INTO cancelled VALUES(?,?)',(self.key(ident),digest))
    def register_call(self,call_id):
        with self.connect() as c:c.execute('INSERT OR IGNORE INTO calls(id) VALUES(?)',(call_id,))
    def close_call(self,call_id):
        with self.connect() as c:c.execute('UPDATE calls SET closed=1 WHERE id=?',(call_id,))
    def pending_calls(self):
        with self.connect() as c:return [r[0] for r in c.execute('SELECT id FROM calls WHERE closed=0')]
    def reserve_response(self,ident,policy):
        p=self.policy()
        if not p.enabled or p.authorization!=policy.authorization or p.expires_at<=time.time():raise PermissionError('realtime_budget_expired')
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT started,responses FROM sessions WHERE id=?',(self.key(ident),)).fetchone()
            if not row or row[1]>=policy.max_responses_per_session or time.time()-row[0]>policy.max_session_seconds:raise PermissionError('realtime_response_budget_exhausted')
            c.execute('UPDATE sessions SET responses=responses+1 WHERE id=?',(self.key(ident),))
    def record(self,session,response,usage):
        # Keep only numeric provider accounting. No arbitrary strings, transcripts or raw events.
        def numeric(obj):
            return {k:numeric(v) if isinstance(v,dict) else v for k,v in obj.items()
                    if isinstance(k,str) and (isinstance(v,dict) or type(v) in (int,float))}
        clean=numeric(usage)
        with self.connect() as c:
            c.execute('INSERT OR IGNORE INTO usage VALUES(?,?,?)',(self.key(session),self.key(response),json.dumps(clean)))
            return c.total_changes>0
    def total_tokens(self,session):
        with self.connect() as c:rows=c.execute('SELECT usage FROM usage WHERE session=?',(self.key(session),)).fetchall()
        return sum(json.loads(row[0]).get('total_tokens',0) for row in rows)
    def status(self):
        p=self.policy()
        with self.connect() as c:
            count=c.execute('SELECT count(*) FROM sessions WHERE authorization=?',(p.authorization,)).fetchone()[0]
        return {'enabled':p.enabled and p.expires_at>time.time(),'audience':p.audience,'sessions_reserved':count,
                'max_sessions':p.max_sessions,'expires_at':p.expires_at,'accepted_as_default':p.accepted_as_default,
                'input_transcription':p.input_transcription,'max_session_seconds':p.max_session_seconds,
                'hard_dollar_cap_guaranteed':False,'contains_conversation_content':False}

def estimate_usd(usage):
    """2026-11-10 official Mini token rates; excludes separately billed input transcription."""
    i=usage.get('input_token_details',{});o=usage.get('output_token_details',{})
    cached=i.get('cached_tokens_details',{})
    values=(i.get('text_tokens',0),i.get('audio_tokens',0),cached.get('text_tokens',0),cached.get('audio_tokens',0),o.get('text_tokens',0),o.get('audio_tokens',0))
    if any(type(v) not in (int,float) or v<0 for v in values):raise ValueError('invalid_usage')
    ti,ai,tc,ac,to,ao=values
    return (max(0,ti-tc)*.6+max(0,ai-ac)*10+tc*.06+ac*.3+to*2.4+ao*20)/1_000_000
