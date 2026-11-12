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
            c.execute('CREATE TABLE IF NOT EXISTS reports(id TEXT PRIMARY KEY,created REAL,payload TEXT)')
    def connect(self):return sqlite3.connect(self.path,timeout=5)
    @staticmethod
    def scope(offer):return hashlib.sha256(json.dumps([offer.device_id,offer.client_id,offer.profile_epoch]).encode()).hexdigest()
    def reserve(self,offer):
        p=self.owner.policy();binding=offer.owner_test_binding or offer.client_id
        if p.hardware_voice and offer.client_id==p.hardware_voice.client_id and binding!=offer.client_id:
            raise PermissionError('hardware_guest_binding_required')
        grant=self.owner.hardware_grant(binding)
        if grant and (offer.client_id!=offer.device_id or offer.owner_test_binding or offer.profile_epoch or
                      offer.confirmed_profile_epoch or offer.personalization_mode!='guest' or offer.expert_quota_consent or
                      offer.conversation_mode!='unified' or offer.remember or offer.speaker_consent or offer.developer_acceptance):
            raise PermissionError('hardware_guest_binding_required')
        if not offer.consent or not self.owner.voice_authorized(binding) or not p.live_enabled:raise PermissionError('live_owner_mode_or_consent_required')
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            if c.execute('SELECT 1 FROM cancelled WHERE id=?',(offer.session_id,)).fetchone():raise ValueError('live_setup_cancelled')
            if c.execute('SELECT 1 FROM calls WHERE id=?',(offer.session_id,)).fetchone():raise ValueError('live_session_already_attempted')
            rows=c.execute('SELECT reserved,seconds,final,origin,reason FROM calls WHERE day=? AND origin NOT LIKE "hardware:%"',(int(time.time()//86400),)).fetchall()
            used=sum((0 if reason=='not_created' else max(15,seconds)) if final else reserved for reserved,seconds,final,_,reason in rows)
            limit=min(p.live_session_seconds,int(p.live_minutes_per_day*60-used))
            origin='developer' if offer.developer_acceptance else 'owner'
            if grant:
                origin='hardware:'+grant.grant_id
                limit=grant.session_seconds
                if grant.expires_at is not None:limit=min(limit,int(grant.expires_at-time.time()))
            if origin=='developer':
                all_dev=c.execute("SELECT reserved,seconds,final,reason FROM calls WHERE origin='developer'").fetchall()
                remaining=p.developer_live_seconds-sum((0 if reason=='not_created' else max(15,seconds)) if final else reserved for reserved,seconds,final,reason in all_dev)
                limit=min(limit,p.developer_live_session_seconds,int(remaining))
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
        with self.connect() as c:return c.execute('SELECT id,provider,cleanup_attempted FROM calls WHERE final=0').fetchall()
    def not_started(self,ident):
        with self.connect() as c:
            row=c.execute('SELECT owner_reservation FROM calls WHERE id=? AND provider IS NULL',(ident,)).fetchone()
            if row:c.execute("UPDATE calls SET final=1,reason='not_created',reserved=0 WHERE id=?",(ident,))
        if row:self.owner.settle(row[0],0)
    def cleanup_claim(self,ident):
        with self.connect() as c:
            c.execute('UPDATE calls SET cleanup_attempted=1 WHERE id=? AND cleanup_attempted=0',(ident,));return c.total_changes>0
    def status(self):
        with self.connect() as c:
            rows=c.execute('SELECT seconds,final,reserved,reason FROM calls WHERE day=?',(int(time.time()//86400),)).fetchall()
            latest=c.execute('SELECT payload FROM reports ORDER BY created DESC LIMIT 1').fetchone()
        return {'model':'gpt-live-1','requested_version':'1.1','model_version_1_1_verified':False,
            'voice_seconds_observed':sum(r[0] for r in rows),'unconfirmed_sessions':sum(not r[1] for r in rows),
            'reserved_seconds_including_pending':sum((0 if r[3]=='not_created' else max(15,r[0])) if r[1] else r[2] for r in rows),
            'voice_usd_per_minute':.05,'backend_billed_separately':True,'cumulative_usage_not_summed':True,
            'hard_dollar_cap_guaranteed':False,'contains_conversation_content':False,'latest_report':json.loads(latest[0]) if latest else None}

    def record_report(self,session,reason):
        allowed={'mode_switch','user_stop','conversation_ended','idle_timeout','session_time_limit','owner_mode_disabled','page_hidden','network_offline','webrtc_failed','microphone_ended','profile_changed','settings_changed','events_disconnected','speaker_changed_or_uncertain','server_shutdown','setup_failed','sideband_closed','provider_closed'}
        keys={'input_start_ms','input_end_ms','first_output_start_ms','client_playback_seen_ms','visual_provisional_scene_sent','visual_provisional_sent','visual_refined_sent'}
        report={'model':'gpt-live-1','reason':reason if reason in allowed else 'other','final_usage_confirmed':session.final_usage_confirmed,
            'unified_mode':getattr(session,'mode_flow',None) is not None,
            'setup_ms':{k:v for k,v in session.timings.items() if k in {'create_ms','attach_and_ack_ms','total_ms'} and type(v) in (int,float)},
            'turns':[ {k:v for k,v in turn.timings.items() if k in keys and type(v) in (int,float)} for turn in session.turns[-64:]],
            'events':{k:v for k,v in session.event_counts.items() if k in {'local_tool_status','conversation_mode_switching','turn_started','backend_status','expert_job','expert_result','meaning_mismatch','visual_response','visual_status','warning','playback_cleared'}},
            'contains_conversation_content':False,'client_playback_is_signal_not_useful_word':True,'physical_iphone_verified':False,
            'clock_domains':{'input_output_offsets':'provider_media_timeline','visual_client_seen':'server_elapsed_since_application_session'}}
        with self.connect() as c:c.execute('INSERT INTO reports VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload',(hashlib.sha256(session.id.encode()).hexdigest(),time.time(),json.dumps(report)))
