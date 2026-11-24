"""Scoped durable timers and at-most-once alarm attempts in Brain's SQLite.

No model, voice session, credentials or device transport is used here. A bound
consumer claims an alarm durably before sending it; losing that delivery never
authorizes another audible attempt. Receipts contain IDs and timing only.
"""
import hashlib
import json
import math
import re
import time
from dataclasses import dataclass
from uuid import uuid4


ALARM_LATE_SECONDS = 120
MAX_DELIVERY_BATCH = 16
MAX_CURRENT_TIMERS = 16
ALARM_RECEIPT_TIMEOUT_SECONDS = 86400
TERMINAL_RECEIPTS = frozenset({'finished', 'cancelled', 'suppressed', 'unknown'})


@dataclass(frozen=True)
class TimerScope:
    device_id: str
    client_id: str | None = None
    profile_epoch: str | None = None

    def __post_init__(self):
        for value, optional in ((self.device_id, False), (self.client_id, True), (self.profile_epoch, True)):
            if value is None and optional:
                continue
            if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,160}', value):
                raise ValueError('invalid_timer_scope')

    @property
    def key(self):
        value = json.dumps([self.device_id, self.client_id, self.profile_epoch], separators=(',', ':'))
        return 'timer-scope:'+hashlib.sha256(value.encode()).hexdigest()


class TimerService:
    def __init__(self, memory, *, clock=None):
        self.memory = memory
        self.clock = clock or time.time
        # Preserve the original five-column table for older routes and rollback.
        # A missing binding is never adopted into a new native principal.
        with memory.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS timers(
                id TEXT PRIMARY KEY,device_id TEXT,conversation_id TEXT,deadline REAL,status TEXT)''')
            db.execute('''CREATE TABLE IF NOT EXISTS timer_action_receipts(
                owner TEXT,action TEXT,payload_hash TEXT,result TEXT,PRIMARY KEY(owner,action))''')
            db.execute('''CREATE TABLE IF NOT EXISTS timer_bindings(
                timer_id TEXT PRIMARY KEY REFERENCES timers(id) ON DELETE CASCADE,
                scope_key TEXT NOT NULL,duration_seconds REAL NOT NULL,revision INTEGER NOT NULL)''')
            db.execute('CREATE INDEX IF NOT EXISTS timer_binding_scope ON timer_bindings(scope_key,timer_id)')
            db.execute('''CREATE TABLE IF NOT EXISTS timer_scope_versions(
                scope_key TEXT PRIMARY KEY,revision INTEGER NOT NULL)''')
            db.execute('''CREATE TABLE IF NOT EXISTS timer_alarm_deliveries(
                alarm_id TEXT PRIMARY KEY,timer_id TEXT UNIQUE NOT NULL REFERENCES timers(id) ON DELETE CASCADE,
                scope_key TEXT NOT NULL,revision INTEGER NOT NULL,expires_at REAL NOT NULL,state TEXT NOT NULL,
                claim_id TEXT,consumer_hash TEXT,claimed_at REAL,updated_at REAL NOT NULL)''')
            db.execute('CREATE INDEX IF NOT EXISTS timer_alarm_scope ON timer_alarm_deliveries(scope_key,state,expires_at)')

    @staticmethod
    def scope(req):
        return req if isinstance(req, TimerScope) else TimerScope(req.device_id,
            getattr(req, 'client_id', None), getattr(req, 'profile_epoch', None))

    def _now(self, now):
        value = self.clock() if now is None else now
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError('invalid_timer_clock')
        return value

    @staticmethod
    def _current(check):
        if check is not None and (not callable(check) or check() is not True):
            raise PermissionError('timer_action_context_changed')

    @staticmethod
    def _bump(db, scope_key):
        db.execute('''INSERT INTO timer_scope_versions VALUES(?,1)
            ON CONFLICT(scope_key) DO UPDATE SET revision=revision+1''', (scope_key,))
        return db.execute('SELECT revision FROM timer_scope_versions WHERE scope_key=?', (scope_key,)).fetchone()[0]

    @staticmethod
    def _action(action_id):
        if not isinstance(action_id, str) or not 1 <= len(action_id) <= 200:
            raise ValueError('timer_action_id_required')
        return hashlib.sha256(action_id.encode()).hexdigest()

    def _receipt(self, db, scope, action_id, payload):
        action = self._action(action_id)
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        row = db.execute('SELECT payload_hash,result FROM timer_action_receipts WHERE owner=? AND action=?',
                         (scope.key, action)).fetchone()
        if row:
            if row['payload_hash'] != digest:
                raise ValueError('action_payload_conflict')
            return action, digest, {**json.loads(row['result']), 'replayed': True}
        return action, digest, None

    @staticmethod
    def _save_receipt(db, scope, action, digest, result):
        db.execute('INSERT INTO timer_action_receipts VALUES(?,?,?,?)',
                   (scope.key, action, digest, json.dumps(result, separators=(',', ':'))))

    @staticmethod
    def _owned_sql():
        # The separate legacy paths retain unbound rows. New native delivery
        # never guesses a client/profile binding from the old device string.
        return 't.device_id=? AND b.scope_key=?'

    @staticmethod
    def _scope_args(scope):
        return scope.device_id, scope.key

    def _rows(self, db, scope, *, active=False, current=False, now=None):
        query = '''SELECT t.*,b.scope_key,b.duration_seconds,b.revision
            FROM timers t LEFT JOIN timer_bindings b ON b.timer_id=t.id WHERE '''+self._owned_sql()
        args = self._scope_args(scope)
        if active:
            query += " AND t.status='running' AND t.deadline>?"
            args += (now,)
        elif current:
            query += " AND t.status IN ('running','expired')"
        return db.execute(query+' ORDER BY t.deadline,t.id', args).fetchall()

    def active(self, req, *, now=None):
        scope, now = self.scope(req), self._now(now)
        with self.memory.connect() as db:
            return [dict(row) for row in self._rows(db, scope, active=True, now=now)]

    def current(self, req, *, now=None):
        """The same announced running/completed set that cancellation targets."""
        scope, now = self.scope(req), self._now(now)
        self.expire_due(now=now)
        with self.memory.connect() as db:
            rows = self._rows(db, scope, current=True, now=now)
            return [dict(row) for row in sorted(rows, key=lambda row:
                (row['status'] != 'running', row['deadline'] if row['status'] == 'running' else -row['deadline'], row['id']))]

    def start(self, req, seconds, *, action_id, is_current=None, now=None):
        if type(seconds) not in (int, float) or not math.isfinite(seconds) or not 1 <= seconds <= 86400:
            raise ValueError('invalid_timer_duration')
        if seconds == int(seconds):
            seconds = int(seconds)
        scope, now = self.scope(req), self._now(now)
        self.expire_due(now=now)
        payload = {'operation': 'start', 'seconds': seconds, 'conversation_id': req.conversation_id}
        with self.memory.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self._current(is_current)
            action, digest, old = self._receipt(db, scope, action_id, payload)
            if old:
                return old
            current = self._rows(db, scope, current=True, now=now)
            if len(current) >= MAX_CURRENT_TIMERS:
                result = {'operation': 'start', 'executed': False,
                          'reason': 'timer_limit_reached', 'limit': MAX_CURRENT_TIMERS,
                          'current_count': len(current)}
                self._save_receipt(db, scope, action, digest, result)
                self._current(is_current)
                return {**result, 'replayed': False}
            ident, deadline = str(uuid4()), now+seconds
            revision = self._bump(db, scope.key)
            db.execute("INSERT INTO timers VALUES(?,?,?,?,'running')",
                       (ident, scope.device_id, req.conversation_id, deadline))
            db.execute('INSERT INTO timer_bindings VALUES(?,?,?,?)', (ident, scope.key, seconds, revision))
            result = {'operation': 'start', 'executed': True, 'timer_id': ident,
                      'deadline': deadline, 'duration_seconds': seconds, 'revision': revision, 'state': 'running'}
            self._save_receipt(db, scope, action, digest, result)
            self._current(is_current)
            return {**result, 'replayed': False}

    @staticmethod
    def _target(target):
        if not isinstance(target, str) or len(target) > 120:
            raise ValueError('invalid_timer_target')
        value = ' '.join(target.casefold().replace('ё', 'е').split())
        if value in {'', 'мой', 'only'}:
            return 'only'
        if value in {'все', 'все мои', 'мои все', 'all'}:
            return 'all'
        ordinal = {'первый': 1, 'второй': 2, 'третий': 3, 'четвертый': 4, 'пятый': 5}.get(value)
        if ordinal is None and re.fullmatch(r'№?\d+', value):
            ordinal = int(value.lstrip('№'))
        return 'ordinal:'+str(ordinal) if ordinal is not None else 'id:'+value

    def cancel(self, req, target='only', *, listed_ids=(), action_id, is_current=None, now=None):
        scope, now = self.scope(req), self._now(now)
        selector = self._target(target)
        self.expire_due(now=now)
        payload = {'operation': 'cancel', 'target': selector, 'conversation_id': req.conversation_id}
        with self.memory.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self._current(is_current)
            action, digest, old = self._receipt(db, scope, action_id, payload)
            if old:
                return old
            rows = self._rows(db, scope, current=True, now=now)
            selected = []
            if selector == 'all' or selector == 'only' and len(rows) == 1:
                selected = rows
            elif selector.startswith('ordinal:'):
                index = int(selector.split(':', 1)[1])-1
                ident = listed_ids[index] if 0 <= index < min(len(listed_ids), 5) else None
                selected = [row for row in rows if row['id'] == ident]
            elif selector.startswith('id:'):
                selected = [row for row in rows if row['id'] == selector[3:]]
            for row in selected:
                revision = self._bump(db, scope.key)
                db.execute("UPDATE timers SET status='cancelled' WHERE id=? AND status IN ('running','expired')", (row['id'],))
                db.execute('UPDATE timer_bindings SET revision=? WHERE timer_id=?', (revision, row['id']))
                db.execute("UPDATE timer_alarm_deliveries SET state='cancelled',updated_at=? WHERE timer_id=? AND state IN ('pending','claimed','started')",
                           (now, row['id']))
            result = {'operation': 'cancel', 'executed': bool(selected),
                      'timer_cancelled_ids': [row['id'] for row in selected],
                      'reason': 'cancelled' if selected else 'timer_selection_required' if rows else 'no_active_timers'}
            self._save_receipt(db, scope, action, digest, result)
            self._current(is_current)
            return {**result, 'replayed': False}

    def expire_due(self, *, now=None):
        """Advance persisted deadlines, independently of any conversation."""
        now = self._now(now)
        with self.memory.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            rows = db.execute('''SELECT t.id,t.deadline,b.scope_key FROM timers t
                JOIN timer_bindings b ON b.timer_id=t.id WHERE t.status='running' AND t.deadline<=?''', (now,)).fetchall()
            for row in rows:
                revision = self._bump(db, row['scope_key'])
                db.execute("UPDATE timers SET status='expired' WHERE id=? AND status='running'", (row['id'],))
                db.execute('UPDATE timer_bindings SET revision=? WHERE timer_id=?', (revision, row['id']))
                expires = row['deadline']+ALARM_LATE_SECONDS
                db.execute('''INSERT OR IGNORE INTO timer_alarm_deliveries
                    (alarm_id,timer_id,scope_key,revision,expires_at,state,updated_at) VALUES(?,?,?,?,?,?,?)''',
                    (str(uuid4()), row['id'], row['scope_key'], revision, expires,
                     'pending' if now < expires else 'suppressed', now))
            db.execute("UPDATE timer_alarm_deliveries SET state='suppressed',updated_at=? WHERE state='pending' AND expires_at<=?", (now, now))
            # A lost terminal receipt never permits another audible attempt.
            # Its timeout does not dismiss the expired timer or free its slot.
            db.execute("""UPDATE timer_alarm_deliveries SET state='unknown',updated_at=?
                WHERE state IN ('claimed','started') AND claimed_at<?""",
                (now, now-ALARM_RECEIPT_TIMEOUT_SECONDS))
            return len(rows)

    def snapshot(self, req, *, now=None):
        scope, now = self.scope(req), self._now(now)
        self.expire_due(now=now)
        with self.memory.connect() as db:
            revision = db.execute('SELECT revision FROM timer_scope_versions WHERE scope_key=?', (scope.key,)).fetchone()
            rows = self._rows(db, scope)
            priority = {'running': 0, 'expired': 1, 'cancelled': 2}
            rows = sorted(rows, key=lambda row: (priority.get(row['status'], 3),
                row['deadline'] if row['status'] == 'running' else -row['revision']))
            timers = []
            for row in rows:
                if row['status'] not in {'running', 'expired', 'cancelled'}:
                    continue
                item = {'timer_id': row['id'], 'revision': row['revision'] or 0, 'state': row['status'],
                        'deadline': row['deadline'], 'remaining_ms': max(0, min(86400000, round((row['deadline']-now)*1000))) if row['status'] == 'running' else 0}
                if row['duration_seconds'] is not None:
                    item['duration_ms'] = round(row['duration_seconds']*1000)
                timers.append(item)
                if len(timers) >= MAX_DELIVERY_BATCH:
                    break
            return {'revision': revision[0] if revision else 0, 'timers': timers}

    def claim_due(self, req, consumer_id, *, now=None, limit=MAX_DELIVERY_BATCH):
        scope, now = self.scope(req), self._now(now)
        if not isinstance(consumer_id, str) or not 1 <= len(consumer_id) <= 200:
            raise ValueError('invalid_timer_consumer')
        if type(limit) is not int or not 1 <= limit <= MAX_DELIVERY_BATCH:
            raise ValueError('invalid_timer_delivery_limit')
        self.expire_due(now=now)
        with self.memory.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            rows = db.execute('''SELECT * FROM timer_alarm_deliveries
                WHERE scope_key=? AND state='pending' AND expires_at>? ORDER BY expires_at,alarm_id LIMIT ?''',
                (scope.key, now, limit)).fetchall()
            alarms = []
            for row in rows:
                claim_id = str(uuid4())
                db.execute("UPDATE timer_alarm_deliveries SET state='claimed',claim_id=?,consumer_hash=?,claimed_at=?,updated_at=? WHERE alarm_id=? AND state='pending'",
                    (claim_id, hashlib.sha256(consumer_id.encode()).hexdigest(), now, now, row['alarm_id']))
                alarms.append({key: row[key] for key in ('alarm_id', 'timer_id', 'revision', 'expires_at')} | {'claim_id': claim_id})
            return alarms

    def ack(self, req, alarm_id, claim_id, state, *, now=None, is_current=None):
        scope, now = self.scope(req), self._now(now)
        if not isinstance(state, str) or state not in {'started', *TERMINAL_RECEIPTS}:
            raise ValueError('invalid_timer_alarm_receipt')
        for ident in (alarm_id, claim_id):
            if not isinstance(ident, str) or not re.fullmatch(r'[a-f0-9-]{36}', ident):
                raise ValueError('invalid_timer_alarm_receipt')
        with self.memory.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self._current(is_current)
            row = db.execute('SELECT state FROM timer_alarm_deliveries WHERE scope_key=? AND alarm_id=? AND claim_id=?',
                             (scope.key, alarm_id, claim_id)).fetchone()
            if not row or row['state'] == 'pending':
                return False
            if row['state'] == state:
                return True
            if row['state'] in TERMINAL_RECEIPTS:
                return False
            db.execute('UPDATE timer_alarm_deliveries SET state=?,updated_at=? WHERE alarm_id=?', (state, now, alarm_id))
            self._current(is_current)
            return True
