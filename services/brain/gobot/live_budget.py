"""Live duration reservations, cumulative usage and terminal confirmation, no transcripts."""
import hashlib,json,sqlite3,time,math
from pathlib import Path

class LiveBudget:
    def __init__(self,root,owner):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True);self.path=self.root/'usage.sqlite';self.owner=owner
        with self.connect() as c:
            c.execute('CREATE TABLE IF NOT EXISTS calls(id TEXT PRIMARY KEY,scope TEXT,provider TEXT,day INTEGER,reserved INTEGER,seconds REAL DEFAULT 0,final INTEGER DEFAULT 0,reason TEXT,owner_reservation TEXT,origin TEXT,cleanup_attempted INTEGER DEFAULT 0)')
            c.execute('CREATE TABLE IF NOT EXISTS commands(session TEXT,id TEXT,PRIMARY KEY(session,id))')
            c.execute('CREATE TABLE IF NOT EXISTS cancelled(id TEXT PRIMARY KEY,scope TEXT)')
    def connect(self):return sqlite3.connect(self.path,timeout=5)
    @staticmethod
    def scope(offer):return hashlib.sha256(json.dumps([offer.device_id,offer.client_id,offer.profile_epoch]).encode()).hexdigest()
    def reserve(self,offer):
        p=self.owner.policy();binding=offer.owner_test_binding or offer.client_id
        if not offer.consent or not self.owner.authorized(binding) or not p.live_enabled:raise PermissionError('live_owner_mode_or_consent_required')
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            if c.execute('SELECT 1 FROM cancelled WHERE id=?',(offer.session_id,)).fetchone():raise ValueError('live_setup_cancelled')
            if c.execute('SELECT 1 FROM calls WHERE id=?',(offer.session_id,)).fetchone():raise ValueError('live_session_already_attempted')
            rows=c.execute('SELECT reserved,seconds,final,origin FROM calls WHERE day=?',(int(time.time()//86400),)).fetchall()
            used=sum(max(15,seconds) if final else reserved for reserved,seconds,final,_ in rows)
            limit=min(p.live_session_seconds,int(p.live_minutes_per_day*60-used))
            origin='developer' if offer.developer_acceptance else 'owner'
            if origin=='developer':
                all_dev=c.execute("SELECT reserved,seconds,final FROM calls WHERE origin='developer'").fetchall()
                remaining=p.developer_live_seconds-sum(max(15,seconds) if final else reserved for reserved,seconds,final in all_dev)
                limit=min(limit,90,int(remaining))
            if limit<15:raise PermissionError('live_duration_budget_exhausted')
            key=self.owner.reserve(binding,'live',offer.session_id,estimate=limit*.05/60,origin=origin)
            c.execute('INSERT INTO calls(id,scope,day,reserved,owner_reservation,origin) VALUES(?,?,?,?,?,?)',(offer.session_id,self.scope(offer),int(time.time()//86400),limit,key,origin))
        return limit
    def registered(self,ident,provider):
        with self.connect() as c:c.execute('UPDATE calls SET provider=? WHERE id=?',(provider,ident))
    def cancel_before_start(self,ident,scope):
        digest=hashlib.sha256(json.dumps(scope).encode()).hexdigest()
        with self.connect() as c:
            previous=c.execute('SELECT scope FROM cancelled WHERE id=?',(ident,)).fetchone()
            if previous and previous[0]!=digest:raise PermissionError('live_session_not_owned')
            c.execute('INSERT OR IGNORE INTO cancelled VALUES(?,?)',(ident,digest))
    def observe(self,ident,seconds,*,final=False,reason=None):
        if type(seconds) not in (int,float) or not math.isfinite(seconds) or not 0<=seconds<=14400:raise ValueError('invalid_live_duration')
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT seconds,final,owner_reservation FROM calls WHERE id=?',(ident,)).fetchone()
            if not row:return
            seconds=max(row[0],seconds)
            c.execute('UPDATE calls SET seconds=?,final=max(final,?),reason=? WHERE id=?',(seconds,int(final),reason if reason in {'close_requested','expired','content','remote_hangup','connection_lost'} else 'unknown',ident))
        if final and not row[1]:self.owner.settle(row[2],max(15,seconds)*.05/60)
    def claim(self,session,command):
        with self.connect() as c:
            c.execute('INSERT OR IGNORE INTO commands VALUES(?,?)',(session,hashlib.sha256(command.encode()).hexdigest()));return c.total_changes>0
    def pending(self):
        with self.connect() as c:return c.execute('SELECT id,provider,cleanup_attempted FROM calls WHERE provider IS NOT NULL AND final=0').fetchall()
    def cleanup_claim(self,ident):
        with self.connect() as c:
            c.execute('UPDATE calls SET cleanup_attempted=1 WHERE id=? AND cleanup_attempted=0',(ident,));return c.total_changes>0
    def status(self):
        with self.connect() as c:rows=c.execute('SELECT seconds,final,reserved FROM calls WHERE day=?',(int(time.time()//86400),)).fetchall()
        return {'model':'gpt-live-1','requested_version':'1.1','model_version_1_1_verified':False,
            'voice_seconds_observed':sum(r[0] for r in rows),'unconfirmed_sessions':sum(not r[1] for r in rows),
            'reserved_seconds_including_pending':sum(max(15,r[0]) if r[1] else r[2] for r in rows),
            'voice_usd_per_minute':.05,'backend_billed_separately':True,'cumulative_usage_not_summed':True,
            'hard_dollar_cap_guaranteed':False,'contains_conversation_content':False}
