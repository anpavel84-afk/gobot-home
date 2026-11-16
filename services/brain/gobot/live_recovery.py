"""Append-only local recovery decisions, never a substitute for provider final usage."""
import json,time
from uuid import uuid4

class LiveRecovery:
    def __init__(self,budget):
        self.budget=budget
        with budget.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS recovery_events(id TEXT PRIMARY KEY,session TEXT,created REAL,kind TEXT,payload TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS resume_approvals(id TEXT PRIMARY KEY,session TEXT,scope TEXT,created REAL,expires REAL,max_new INTEGER,owner TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS resume_uses(approval TEXT,new_session TEXT,PRIMARY KEY(approval,new_session))')

    def orphan(self,ident,scope,*,local_evidence):
        required={'gateway_idle','brain_idle','old_relay_absent'}
        if set(local_evidence)!=required or not all(local_evidence[k] is True for k in required):
            raise ValueError('local_cleanup_not_verified')
        with self.budget.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT scope,final FROM calls WHERE id=?',(ident,)).fetchone()
            if not row or row[0]!=scope:raise PermissionError('recovery_scope_mismatch')
            if row[1]:raise ValueError('session_already_finalized')
            if db.execute("SELECT 1 FROM recovery_events WHERE session=? AND kind='orphaned_unconfirmed'",(ident,)).fetchone():return False
            db.execute('INSERT INTO recovery_events VALUES(?,?,?,?,?)',(uuid4().hex,ident,time.time(),
                'orphaned_unconfirmed',json.dumps({'local_evidence':local_evidence,'provider_confirmed':False})))
        return True

    def approve(self,ident,scope,*,owner_binding,risk_ack,max_new_sessions=1,expires_at):
        if not self.budget.owner.bound(owner_binding) or risk_ack is not True:
            raise PermissionError('explicit_owner_risk_ack_required')
        if type(max_new_sessions) is not int or not 1<=max_new_sessions<=50:
            raise ValueError('invalid_recovery_allowance')
        if type(expires_at) not in (int,float):raise ValueError('recovery_expiry_required')
        if not time.time()<expires_at<=time.time()+86400:raise ValueError('recovery_expiry_required')
        with self.budget.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT scope,final FROM calls WHERE id=?',(ident,)).fetchone()
            if not row or row[0]!=scope or row[1]:raise ValueError('unconfirmed_session_required')
            if not db.execute("SELECT 1 FROM recovery_events WHERE session=? AND kind='orphaned_unconfirmed'",(ident,)).fetchone():
                raise ValueError('local_cleanup_not_verified')
            if self._approval(db,ident,scope):raise ValueError('recovery_approval_already_active')
            key=uuid4().hex
            db.execute('INSERT INTO resume_approvals VALUES(?,?,?,?,?,?,?)',(key,ident,scope,time.time(),expires_at,max_new_sessions,owner_binding))
            db.execute('INSERT INTO recovery_events VALUES(?,?,?,?,?)',(uuid4().hex,ident,time.time(),'owner_resume_approved',
                json.dumps({'approval':key,'max_new_sessions':max_new_sessions,'risk_ack':True,'provider_confirmed':False})))
        return key

    def _approval(self,db,ident,scope):
        row=db.execute('''SELECT a.id,a.owner FROM resume_approvals a JOIN calls c ON c.id=a.session
            WHERE a.session=? AND a.scope=? AND c.scope=a.scope AND c.final=0 AND a.expires>?
            AND (SELECT count(*) FROM resume_uses u WHERE u.approval=a.id)<a.max_new
            ORDER BY a.created DESC LIMIT 1''',(ident,scope,time.time())).fetchone()
        return row if row and self.budget.owner.bound(row[1]) else None

    def may_resume(self,ident,scope):
        with self.budget.connect() as db:return bool(self._approval(db,ident,scope))

    def consume(self,db,ident,offer):
        approval=self._approval(db,ident,self.budget.scope(offer))
        if not approval:raise PermissionError('recovery_allowance_exhausted')
        db.execute('INSERT INTO resume_uses VALUES(?,?)',(approval[0],offer.session_id))
        db.execute('INSERT INTO recovery_events VALUES(?,?,?,?,?)',(uuid4().hex,ident,time.time(),'new_session_admitted',
            json.dumps({'new_session':offer.session_id,'approval':approval[0],'provider_confirmed':False})))

    def status(self):
        with self.budget.connect() as db:
            count=db.execute("SELECT count(DISTINCT e.session) FROM recovery_events e JOIN calls c ON c.id=e.session WHERE e.kind='orphaned_unconfirmed' AND c.final=0").fetchone()[0]
        return {'orphaned_unconfirmed':count,'provider_confirmation_inferred':False}
