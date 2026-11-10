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
            c.execute('CREATE TABLE IF NOT EXISTS reports(session TEXT PRIMARY KEY,created REAL,report TEXT)')
            c.execute('CREATE TABLE IF NOT EXISTS commands(session TEXT,id TEXT,PRIMARY KEY(session,id))')
    def connect(self):return sqlite3.connect(self.path,timeout=5)
    def policy(self):
        if not self.policy_path.exists():return RealtimePolicy()
        return RealtimePolicy.model_validate_json(self.policy_path.read_text(encoding='utf-8'))
    @staticmethod
    def key(ident):return hashlib.sha256(ident.encode()).hexdigest()
    @staticmethod
    def active(policy):return policy.enabled and bool(policy.authorization) and (policy.expires_at is None or policy.expires_at>time.time())
    def reserve_session(self,ident,consent,client_id=None):
        p=self.policy()
        if not (self.active(p) and consent):raise PermissionError('realtime_budget_or_consent_required')
        if p.allowed_client_id and p.allowed_client_id!=client_id:raise PermissionError('realtime_trial_client_not_allowed')
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            if c.execute('SELECT 1 FROM cancelled WHERE id=?',(self.key(ident),)).fetchone():raise ValueError('realtime_session_cancelled')
            if c.execute('SELECT 1 FROM sessions WHERE id=?',(self.key(ident),)).fetchone():raise ValueError('realtime_session_already_attempted')
            count=c.execute('SELECT count(*) FROM sessions WHERE authorization=?',(p.authorization,)).fetchone()[0]
            if p.max_sessions is not None and count>=p.max_sessions:raise PermissionError('realtime_session_budget_exhausted')
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
        if not self.active(p) or p.authorization!=policy.authorization:raise PermissionError('realtime_budget_expired')
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT started,responses FROM sessions WHERE id=?',(self.key(ident),)).fetchone()
            if not row or (policy.max_responses_per_session is not None and row[1]>=policy.max_responses_per_session) or (policy.max_session_seconds is not None and time.time()-row[0]>policy.max_session_seconds):raise PermissionError('realtime_response_budget_exhausted')
            c.execute('UPDATE sessions SET responses=responses+1 WHERE id=?',(self.key(ident),))
    def claim_command(self,session,ident):
        with self.connect() as c:
            c.execute('INSERT OR IGNORE INTO commands VALUES(?,?)',(self.key(session),self.key(ident)))
            return c.total_changes>0
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
    def record_report(self,session,timings,turns,*,close_reason='unknown',lifetime_ms=None,provider_errors=None,completion_counts=None,alignment_counts=None):
        # Explicit allowlist: captions, queries, speaker IDs and raw audio cannot enter this ledger.
        setup_keys={'call_created','sideband_connected','settings_acknowledged'}
        turn_keys={'input_ended','response_created','answer_transcript','output_buffer_started','client_playback','client_playback_stopped'}
        reasons={'closed','unknown','client_closed','user_stop','page_hidden','network_offline','webrtc_failed','webrtc_disconnected','audio_suspended','audio_play_denied','microphone_ended','events_disconnected','provider_error','server_closed','setup_failed','capture_cancelled','settings_changed','session_time_limit','budget_expired','idle_timeout','followup_timeout','profile_authorization_revoked','sideband_closed','client_events_disconnected','command_failed','observed_token_limit','response_budget_exhausted','profile_changed','profile_or_device_changed','server_shutdown','conversation_ended','speaker_changed_or_uncertain','speaker_profile_mismatch'}
        error_codes={'response_cancel_not_active','input_audio_buffer_commit_empty','input_audio_buffer_commit_too_small','conversation_already_has_active_response','rate_limit_exceeded','insufficient_quota','invalid_api_key','server_error','invalid_request_error','other'}
        def clean(values,keys):
            import math
            return {k:round(v,2) for k,v in values.items() if k in keys and type(v) in (int,float) and math.isfinite(v) and v>=0}
        with self.connect() as c:
            usage=[json.loads(r[0]) for r in c.execute('SELECT usage FROM usage WHERE session=?',(self.key(session),))]
            row=c.execute('SELECT responses FROM sessions WHERE id=?',(self.key(session),)).fetchone()
            report={'setup_ms':clean(timings,setup_keys),'turns_ms':[clean(t,turn_keys) for t in turns],
                    'response_attempts':row[0] if row else 0,'usage_responses_received':len(usage),
                    'reported_tokens':sum(u.get('total_tokens',0) for u in usage),
                    'estimated_response_usd_excluding_transcription':sum(estimate_usd(u) for u in usage),
                    'client_audio_signal_is_not_acoustic_acceptance':True,'contains_conversation_content':False}
            report['close_reason']=close_reason if close_reason in reasons else 'unknown'
            report['lifecycle_ms']=clean({'lifetime':lifetime_ms},{'lifetime'})
            report['provider_errors']={k:v for k,v in (provider_errors or {}).items() if k in error_codes and type(v) is int and 0<v<=1000}
            report['completion_counts']={k:v for k,v in (completion_counts or {}).items() if k in {'max_output_tokens','completed','cancelled','failed','incomplete','other'} and type(v) is int and 0<v<=1000}
            report['alignment_counts']={k:v for k,v in (alignment_counts or {}).items() if k in {'match','suspected_mismatch'} and type(v) is int and 0<v<=1000}
            c.execute('INSERT OR IGNORE INTO reports VALUES(?,?,?)',(self.key(session),time.time(),json.dumps(report)))
    def latest_report(self):
        with self.connect() as c:row=c.execute('SELECT report FROM reports ORDER BY created DESC LIMIT 1').fetchone()
        return json.loads(row[0]) if row else None
    def status(self):
        p=self.policy()
        with self.connect() as c:
            count=c.execute('SELECT count(*) FROM sessions WHERE authorization=?',(p.authorization,)).fetchone()[0]
        return {'enabled':self.active(p),'audience':p.audience,'sessions_reserved':count,
                'max_sessions':p.max_sessions,'expires_at':p.expires_at,'accepted_as_default':p.accepted_as_default,
                'sessions_remaining':None if p.max_sessions is None else max(0,p.max_sessions-count),
                'unlimited_manual_testing':p.audience=='owner_interactive' and p.max_sessions is None and p.max_responses_per_session is None,
                'input_transcription':p.input_transcription,'max_session_seconds':p.max_session_seconds,
                'max_responses_per_session':p.max_responses_per_session,'max_output_tokens':p.max_output_tokens,
                'client_bound':bool(p.allowed_client_id),'expert_jobs_allowed':p.expert_jobs_allowed,
                'image_generation_allowed':p.image_generation_allowed,'latest_report':self.latest_report(),
                'hard_dollar_cap_guaranteed':False,'contains_conversation_content':False}

def estimate_usd(usage):
    """2026-11-10 official Mini token rates; excludes separately billed input transcription."""
    i=usage.get('input_token_details',{});o=usage.get('output_token_details',{})
    cached=i.get('cached_tokens_details',{})
    values=(i.get('text_tokens',0),i.get('audio_tokens',0),cached.get('text_tokens',0),cached.get('audio_tokens',0),o.get('text_tokens',0),o.get('audio_tokens',0))
    if any(type(v) not in (int,float) or v<0 for v in values):raise ValueError('invalid_usage')
    ti,ai,tc,ac,to,ao=values
    return (max(0,ti-tc)*.6+max(0,ai-ac)*10+tc*.06+ac*.3+to*2.4+ao*20)/1_000_000
