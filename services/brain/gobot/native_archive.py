"""Owner-enabled device conversation archive in Brain's existing SQLite.

The enrolled device binding is not a Family identity or a spending grant. Text,
FTS and source notes use the existing plaintext archive under the Windows user's
filesystem permissions. No audio, journal import, model or provider is used here.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import json
import re
import sqlite3
import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


DEFAULT_POLICY = {'write_enabled': False, 'read_enabled': False,
                  'retention_days': 0, 'timezone': 'UTC'}
MAX_ANSWER = 64000
SCHEMA = '''
CREATE TABLE IF NOT EXISTS native_archive_scopes(
 binding_key TEXT PRIMARY KEY,archive_owner TEXT UNIQUE NOT NULL,
 revision INTEGER NOT NULL,generation INTEGER NOT NULL,policy TEXT NOT NULL,
 created REAL NOT NULL,updated REAL NOT NULL,last_write_at REAL);
CREATE TABLE IF NOT EXISTS native_archive_turns(
 binding_key TEXT NOT NULL REFERENCES native_archive_scopes(binding_key),
 source_turn_id TEXT NOT NULL,archive_turn_id TEXT UNIQUE NOT NULL REFERENCES turns(id) ON DELETE CASCADE,
 input_revision INTEGER NOT NULL,accepted_at REAL NOT NULL,
 PRIMARY KEY(binding_key,source_turn_id));
CREATE TABLE IF NOT EXISTS native_archive_sources(
 message_id INTEGER PRIMARY KEY REFERENCES messages(id) ON DELETE CASCADE,
 binding_key TEXT NOT NULL REFERENCES native_archive_scopes(binding_key),
 source_turn_id TEXT NOT NULL,component TEXT NOT NULL,source_revision INTEGER NOT NULL,
 heard INTEGER NOT NULL,complete INTEGER NOT NULL,provenance TEXT NOT NULL,
 aliases TEXT NOT NULL,updated REAL NOT NULL,
 UNIQUE(binding_key,source_turn_id,component));
CREATE TABLE IF NOT EXISTS native_archive_operations(
 binding_key TEXT NOT NULL,operation_hash TEXT NOT NULL,actor_hash TEXT NOT NULL,
 payload_hash TEXT NOT NULL,applied_revision INTEGER NOT NULL,created REAL NOT NULL,
 PRIMARY KEY(binding_key,operation_hash));
CREATE INDEX IF NOT EXISTS native_archive_turn_age ON native_archive_turns(binding_key,accepted_at);
CREATE INDEX IF NOT EXISTS native_archive_source_turn ON native_archive_sources(binding_key,source_turn_id);
'''


def _hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class ArchiveBinding:
    device_id: str
    client_id: str
    owner_id: str

    def __post_init__(self):
        if (not isinstance(self.device_id, str) or
                not re.fullmatch(r'[A-Za-z0-9_.:-]{1,100}', self.device_id) or
                self.device_id.startswith(('personal:', 'family:', 'realtime-guest:')) or
                self.client_id != self.device_id or not isinstance(self.owner_id, str) or
                not self.owner_id.startswith(self.device_id+'@') or
                not re.fullmatch(r'[A-Za-z0-9_.:@-]{3,512}', self.owner_id) or
                len(self.owner_id) <= len(self.device_id)+1):
            raise ValueError('archive_binding_invalid')

    @property
    def key(self):
        return _hash([self.device_id, self.client_id, self.owner_id])

    @property
    def archive_owner(self):
        return 'device-archive:'+self.key


def enrolled_binding(devices, device_id, client_id):
    """Resolve an existing row without creating a device/profile on a read."""
    from .device_contract import DeviceProfile
    path = devices.db
    if not path.is_file() or path.is_symlink():
        raise PermissionError('archive_binding_invalid')
    with sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True, timeout=3) as db:
        rows = db.execute('SELECT owner,profile FROM profiles WHERE substr(owner,1,?)=?',
                          (len(device_id)+1, device_id+'@')).fetchall()
    matches = []
    for owner, raw in rows:
        profile = DeviceProfile.model_validate_json(raw)
        if profile.client_id == client_id and profile.client_kind == 'spotpear':
            matches.append(ArchiveBinding(device_id, client_id, owner))
    if len(matches) != 1:
        raise PermissionError('archive_binding_invalid')
    return matches[0]


def validate_policy(values):
    if not isinstance(values, dict) or set(values) != set(DEFAULT_POLICY):
        raise ValueError('archive_policy_fields')
    if any(type(values[name]) is not bool for name in ('write_enabled', 'read_enabled')):
        raise ValueError('archive_policy_boolean')
    days = values['retention_days']
    if type(days) is not int or not 0 <= days <= 36500:
        raise ValueError('archive_retention_range')
    zone = values['timezone']
    if not isinstance(zone, str) or not 1 <= len(zone) <= 80:
        raise ValueError('archive_timezone_invalid')
    try:
        ZoneInfo(zone)
    except (ValueError, ZoneInfoNotFoundError):
        raise ValueError('archive_timezone_invalid') from None
    return {name: values[name] for name in DEFAULT_POLICY}


def _current(check):
    if check is not None and (not callable(check) or check() is not True):
        raise PermissionError('archive_context_changed')


def _ident(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,180}', value):
        raise ValueError('archive_source_invalid')
    return value


def _aliases(values):
    if not isinstance(values, (tuple, list)) or len(values) > 8:
        raise ValueError('archive_source_invalid')
    return json.dumps(list(dict.fromkeys(_ident(value) for value in values)))


class NativeArchiveService:
    def __init__(self, memory, *, clock=None):
        self.memory = memory
        self.clock = clock or time.time
        self.last_errors = {}
        self.pending_writes = {}
        self._writes = None
        self._writer = None
        self._closed = False
        with memory.connect() as db:
            db.executescript(SCHEMA)

    @staticmethod
    def _binding(binding):
        if not isinstance(binding, ArchiveBinding):
            raise ValueError('archive_binding_invalid')
        return binding

    @staticmethod
    def _scope(db, binding):
        row = db.execute('SELECT * FROM native_archive_scopes WHERE binding_key=? AND archive_owner=?',
                         (binding.key, binding.archive_owner)).fetchone()
        if row is None:
            return {'revision': 0, 'generation': 0, 'policy': dict(DEFAULT_POLICY)}
        result = dict(row)
        result['policy'] = validate_policy(json.loads(result['policy']))
        return result

    def policy(self, binding):
        self._binding(binding)
        with self.memory.connect() as db:
            row = self._scope(db, binding)
        return {key: row[key] for key in ('revision', 'generation', 'policy')}

    def current(self, binding, generation, *, read=False, write=False):
        try:
            row = self.policy(binding)
            return (type(generation) is int and row['generation'] == generation and
                    (not read or row['policy']['read_enabled']) and
                    (not write or row['policy']['write_enabled']))
        except (ValueError, OSError, sqlite3.Error):
            return False

    @staticmethod
    def _receipt_keys(operation_id, actor_id):
        if not isinstance(operation_id, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,120}', operation_id):
            raise ValueError('archive_operation_id_required')
        if not isinstance(actor_id, str) or not 1 <= len(actor_id) <= 512:
            raise PermissionError('archive_owner_required')
        return _hash(operation_id), _hash(actor_id)

    def _status(self, db, binding):
        row = self._scope(db, binding)
        stats = db.execute('''SELECT count(*) AS turns,min(accepted_at) AS oldest,max(accepted_at) AS newest
            FROM native_archive_turns WHERE binding_key=?''', (binding.key,)).fetchone()
        messages = db.execute('SELECT count(*) FROM native_archive_sources WHERE binding_key=?', (binding.key,)).fetchone()[0]
        bound_topics='SELECT DISTINCT tt.topic_id FROM turn_topics tt JOIN native_archive_turns n ON n.archive_turn_id=tt.turn_id WHERE n.binding_key=?'
        topics = db.execute('SELECT count(*) FROM topics WHERE id IN ('+bound_topics+')', (binding.key,)).fetchone()[0]
        blocks = db.execute('SELECT count(*) FROM topic_summaries WHERE topic_id IN ('+bound_topics+')', (binding.key,)).fetchone()[0]
        backlog = db.execute('SELECT count(*) FROM memory_jobs WHERE topic_id IN ('+bound_topics+')', (binding.key,)).fetchone()[0]
        return {'available': True, 'policy': row['policy'], 'revision': row['revision'],
                'generation': row['generation'], 'counts': {'turns': stats['turns'], 'messages': messages,
                    'topics': topics, 'blocks': blocks, 'backlog': backlog+self.pending_writes.get(binding.key,0)},
                'oldest_at': stats['oldest'], 'newest_at': stats['newest'],
                'last_write_at': row.get('last_write_at'), 'last_error': self.last_errors.get(binding.key),
                'storage': 'sqlite_plaintext_windows_acl', 'coverage': 'since_enabled',
                'private_archive': False}

    def status(self, binding, *, operation_id=None, actor_id=None):
        self._binding(binding)
        self.expire(binding)
        with self.memory.connect() as db:
            result = self._status(db, binding)
            if operation_id is not None:
                operation, actor = self._receipt_keys(operation_id, actor_id)
                row = db.execute('SELECT applied_revision FROM native_archive_operations '
                    'WHERE binding_key=? AND operation_hash=? AND actor_hash=?', (binding.key, operation, actor)).fetchone()
                result['operation'] = ({'id': operation_id, 'applied_revision': row[0], 'replayed': True}
                                       if row else None)
        return result

    def configure(self, binding, values, expected_revision, *, operation_id, actor_id, is_current=None):
        return self._change(binding, 'configure', validate_policy(values), expected_revision,
                            operation_id, actor_id, is_current)

    def clear(self, binding, expected_revision, *, operation_id, actor_id, is_current=None):
        return self._change(binding, 'clear', None, expected_revision, operation_id, actor_id, is_current)

    def _change(self, binding, action, values, expected_revision, operation_id, actor_id, is_current):
        self._binding(binding)
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError('archive_revision_conflict')
        operation, actor = self._receipt_keys(operation_id, actor_id)
        payload = _hash([action, values, expected_revision])
        now = self.clock()
        with self.memory.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            _current(is_current)
            receipt = db.execute('SELECT * FROM native_archive_operations WHERE binding_key=? AND operation_hash=?',
                                 (binding.key, operation)).fetchone()
            if receipt:
                if receipt['actor_hash'] != actor or receipt['payload_hash'] != payload:
                    raise ValueError('archive_operation_conflict')
                result = self._status(db, binding)
                result['operation'] = {'id': operation_id, 'applied_revision': receipt['applied_revision'], 'replayed': True}
                _current(is_current)
                return result
            row = self._scope(db, binding)
            if row['revision'] != expected_revision:
                raise ValueError('archive_revision_conflict')
            revision, generation = row['revision']+1, row['generation']+1
            policy = values if action == 'configure' else row['policy']
            db.execute('''INSERT INTO native_archive_scopes VALUES(?,?,?,?,?,?,?,NULL)
                ON CONFLICT(binding_key) DO UPDATE SET revision=excluded.revision,generation=excluded.generation,
                policy=excluded.policy,updated=excluded.updated''',
                (binding.key, binding.archive_owner, revision, generation, json.dumps(policy), now, now))
            if action == 'clear':
                # This owner is derived from an exact enrolled binding, never a
                # caller-selected Family owner. Foreign/legacy rows are untouched.
                rows = db.execute('''SELECT n.archive_turn_id,tt.topic_id FROM native_archive_turns n
                    JOIN turn_topics tt ON tt.turn_id=n.archive_turn_id WHERE n.binding_key=?''', (binding.key,)).fetchall()
                self._remove_turns(db, binding, rows)
                db.execute('UPDATE native_archive_scopes SET last_write_at=NULL WHERE binding_key=?', (binding.key,))
            else:
                self._expire(db, binding, policy, now)
            db.execute('INSERT INTO native_archive_operations VALUES(?,?,?,?,?,?)',
                       (binding.key, operation, actor, payload, revision, now))
            _current(is_current)
            result = self._status(db, binding)
            result['operation'] = {'id': operation_id, 'applied_revision': revision, 'replayed': False}
            return result

    def _expire(self, db, binding, policy, now):
        if not policy['retention_days']:
            return 0
        rows = db.execute('''SELECT n.archive_turn_id,tt.topic_id FROM native_archive_turns n
            JOIN turn_topics tt ON tt.turn_id=n.archive_turn_id
            WHERE n.binding_key=? AND n.accepted_at<?''',
            (binding.key, now-policy['retention_days']*86400)).fetchall()
        if not rows:
            return 0
        self._remove_turns(db, binding, rows)
        # Expiry revokes any source snapshot already in flight, not just its SQL row.
        db.execute('UPDATE native_archive_scopes SET generation=generation+1,updated=? WHERE binding_key=?',
                   (now, binding.key))
        return len(rows)

    @staticmethod
    def _remove_turns(db, binding, rows):
        conversations=set()
        episodes=set()
        for row in rows:
            linked=db.execute('SELECT t.conversation_id,tt.episode_id FROM turns t JOIN turn_topics tt ON tt.turn_id=t.id WHERE t.id=?',(row['archive_turn_id'],)).fetchone()
            if linked:
                conversations.add(linked['conversation_id']);episodes.add(linked['episode_id'])
        for topic in {row['topic_id'] for row in rows}:
            db.execute('UPDATE topics SET generation=generation+1 WHERE id=?', (topic,))
            db.execute('DELETE FROM topic_summaries WHERE topic_id=?', (topic,))
            db.execute('DELETE FROM memory_jobs WHERE topic_id=?', (topic,))
        for row in rows:
            db.execute('DELETE FROM messages WHERE turn_id=?', (row['archive_turn_id'],))
            db.execute('DELETE FROM turns WHERE id=?', (row['archive_turn_id'],))
        for episode in episodes:
            db.execute('DELETE FROM episodes WHERE id=? AND NOT EXISTS (SELECT 1 FROM archive_messages a WHERE a.episode_id=episodes.id)', (episode,))
        for conversation in conversations:
            db.execute('DELETE FROM conversations WHERE id=? AND device_id=? AND NOT EXISTS '
                       '(SELECT 1 FROM turns t WHERE t.conversation_id=conversations.id)', (conversation,binding.archive_owner))
        for topic in {row['topic_id'] for row in rows}:
            db.execute('DELETE FROM topics WHERE id=? AND owner=? AND NOT EXISTS '
                       '(SELECT 1 FROM episodes e WHERE e.topic_id=topics.id)', (topic,binding.archive_owner))

    def expire(self, binding=None):
        if binding is not None:
            self._binding(binding)
        now = self.clock()
        with self.memory.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            rows = db.execute('SELECT * FROM native_archive_scopes'+
                              (' WHERE binding_key=?' if binding else ''),
                              (binding.key,) if binding else ()).fetchall()
            total = 0
            for row in rows:
                policy = validate_policy(json.loads(row['policy']))
                # No profile data is reconstructed from archive content.
                scope = binding if binding else _StoredBinding(row['binding_key'], row['archive_owner'])
                total += self._expire(db, scope, policy, now)
            return total

    def _write_scope(self, db, binding, generation, is_current):
        _current(is_current)
        row = self._scope(db, binding)
        if row['generation'] != generation:
            raise PermissionError('archive_context_changed')
        if not row['policy']['write_enabled']:
            raise PermissionError('archive_disabled')
        return row

    def record_question(self, binding, source_turn_id, conversation_id, text, *, generation,
                        input_revision=1, aliases=(), accepted_at=None, is_current=None):
        from .models import ChatRequest
        self._binding(binding)
        _ident(source_turn_id); _ident(conversation_id)
        if not isinstance(text, str) or not text.strip() or len(text) > 8000 or type(input_revision) is not int or input_revision < 1:
            raise ValueError('archive_source_invalid')
        encoded_aliases, now = _aliases(aliases), self.clock()
        accepted_at = now if accepted_at is None else accepted_at
        if type(accepted_at) not in (int,float) or not 0 <= accepted_at <= now+5:
            raise ValueError('archive_source_invalid')
        with self.memory.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self._write_scope(db, binding, generation, is_current)
            old = db.execute('''SELECT n.*,m.content,s.message_id FROM native_archive_turns n
                JOIN native_archive_sources s ON s.binding_key=n.binding_key AND s.source_turn_id=n.source_turn_id AND s.component='question'
                JOIN messages m ON m.id=s.message_id WHERE n.binding_key=? AND n.source_turn_id=?''',
                (binding.key, source_turn_id)).fetchone()
            if old:
                if old['content'] != text or old['input_revision'] != input_revision:
                    raise ValueError('archive_source_conflict')
                _current(is_current)
                return {'recorded': True, 'replayed': True, 'source_id': 'archive:'+str(old['message_id'])}
            conversation = 'na-'+_hash([binding.key, conversation_id])
            turn_id = 'na-'+_hash([binding.key, source_turn_id])
            db.execute('INSERT OR IGNORE INTO conversations VALUES(?,?,?)', (conversation, binding.archive_owner, accepted_at))
            db.execute('INSERT INTO turns VALUES(?,?,?,?,?,?,?,?)',
                       (turn_id, conversation, _hash([text, input_revision]), 'incomplete', 'native_input', '[]', '', now))
            message_id = db.execute("INSERT INTO messages(conversation_id,role,content,provider,turn_id,created) VALUES(?,'user',?,'input',?,?)",
                                    (conversation, text, turn_id, accepted_at)).lastrowid
            req = ChatRequest(text=text, device_id=binding.archive_owner, conversation_id=conversation,
                              turn_id=turn_id, remember=True)
            self.memory.archive.begin(db, req, message_id, namespace='production', now=accepted_at,
                                      native_binding=binding.key)
            db.execute("UPDATE archive_messages SET status='completed' WHERE message_id=?", (message_id,))
            topic = db.execute('SELECT topic_id FROM turn_topics WHERE turn_id=?', (turn_id,)).fetchone()[0]
            self.memory.archive._index(db, message_id, binding.archive_owner, topic, text, accepted_at)
            db.execute('INSERT INTO native_archive_turns VALUES(?,?,?,?,?)',
                       (binding.key, source_turn_id, turn_id, input_revision, accepted_at))
            db.execute('INSERT INTO native_archive_sources VALUES(?,?,?,?,?,1,1,?,?,?)',
                       (message_id, binding.key, source_turn_id, 'question', input_revision,
                        'user_question' if '?' in text else 'user_utterance', encoded_aliases, now))
            self._queued_notes(db, topic)
            db.execute('UPDATE native_archive_scopes SET last_write_at=? WHERE binding_key=?', (now, binding.key))
            _current(is_current)
            return {'recorded': True, 'replayed': False, 'source_id': 'archive:'+str(message_id)}

    def record_answer(self, binding, source_turn_id, text, *, generation, component='fast',
                      source_revision=1, provider='native', heard=False, complete=True,
                      aliases=(), played_at=None, is_current=None):
        self._binding(binding); _ident(source_turn_id); _ident(component)
        if heard is not True:
            return {'recorded': False, 'reason': 'playback_unconfirmed'}
        if (not isinstance(text, str) or not text.strip() or len(text) > MAX_ANSWER or
                type(source_revision) is not int or source_revision < 1 or type(complete) is not bool or
                not isinstance(provider, str) or not 1 <= len(provider) <= 120 or provider in {'mock','bridge:mock'}):
            raise ValueError('archive_source_invalid')
        encoded_aliases, now = _aliases(aliases), self.clock()
        played_at = now if played_at is None else played_at
        if type(played_at) not in (int,float) or not 0 <= played_at <= now+5:
            raise ValueError('archive_source_invalid')
        with self.memory.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self._write_scope(db, binding, generation, is_current)
            turn = db.execute('''SELECT n.*,t.conversation_id,tt.topic_id,tt.episode_id FROM native_archive_turns n
                JOIN turns t ON t.id=n.archive_turn_id JOIN turn_topics tt ON tt.turn_id=t.id
                WHERE n.binding_key=? AND n.source_turn_id=?''', (binding.key, source_turn_id)).fetchone()
            if not turn:
                raise PermissionError('archive_context_changed')
            old = db.execute('''SELECT s.*,m.content FROM native_archive_sources s JOIN messages m ON m.id=s.message_id
                WHERE s.binding_key=? AND s.source_turn_id=? AND s.component=?''',
                (binding.key, source_turn_id, component)).fetchone()
            if old and old['source_revision'] >= source_revision:
                if old['source_revision'] == source_revision and (old['content'] != text or bool(old['complete']) != complete):
                    raise ValueError('archive_source_conflict')
                _current(is_current)
                return {'recorded': True, 'replayed': True, 'source_id': 'archive:'+str(old['message_id'])}
            if old:
                if not text.startswith(old['content']):
                    raise ValueError('archive_source_conflict')
                message_id = old['message_id']
                db.execute('DELETE FROM retrieval_chunks WHERE message_id=?', (message_id,))
                db.execute('UPDATE messages SET content=?,provider=? WHERE id=?', (text, provider, message_id))
                db.execute('UPDATE native_archive_sources SET source_revision=?,complete=?,aliases=?,updated=? WHERE message_id=?',
                           (source_revision, int(complete), encoded_aliases, now, message_id))
                db.execute('DELETE FROM topic_summaries WHERE topic_id=?', (turn['topic_id'],))
                db.execute('UPDATE topics SET generation=generation+1 WHERE id=?', (turn['topic_id'],))
            else:
                message_id = db.execute("INSERT INTO messages(conversation_id,role,content,provider,turn_id,created) VALUES(?,'assistant',?,?,?,?)",
                    (turn['conversation_id'], text, provider, turn['archive_turn_id'], played_at)).lastrowid
                db.execute('INSERT INTO archive_messages VALUES(?,?,?,?,?,?)',
                    (message_id, binding.archive_owner, turn['topic_id'], turn['episode_id'], 'production', 'completed'))
                db.execute('INSERT INTO native_archive_sources VALUES(?,?,?,?,?,1,?,?,?,?)',
                    (message_id, binding.key, source_turn_id, component, source_revision, int(complete),
                     'assistant_statement', encoded_aliases, now))
            self.memory.archive._index(db, message_id, binding.archive_owner, turn['topic_id'], text, played_at)
            db.execute('UPDATE turns SET status=?,provider=?,updated=? WHERE id=?',
                       ('completed' if complete else 'incomplete', provider, now, turn['archive_turn_id']))
            self._queued_notes(db, turn['topic_id'])
            db.execute('UPDATE native_archive_scopes SET last_write_at=? WHERE binding_key=?', (now, binding.key))
            _current(is_current)
            return {'recorded': True, 'replayed': False, 'source_id': 'archive:'+str(message_id)}

    @staticmethod
    def _queued_notes(db, topic):
        generation = db.execute('SELECT generation FROM topics WHERE id=?', (topic,)).fetchone()[0]
        if db.execute('SELECT count(*) FROM memory_jobs').fetchone()[0] < 32:
            db.execute('INSERT OR REPLACE INTO memory_jobs VALUES(?,?,?)', (topic, generation, time.time()))

    @staticmethod
    def _period(query, zone, now):
        local = datetime.fromtimestamp(now, ZoneInfo(zone))
        today = local.replace(hour=0, minute=0, second=0, microsecond=0)
        lower = query.lower()
        days = 2 if re.search(r'\bпозавчера(?:шн\w*)?\b', lower) else 1 if re.search(r'\bвчера(?:шн\w*)?\b', lower) else 0 if re.search(r'\bсегодня(?:шн\w*)?\b', lower) else None
        if days is not None:
            start = today-timedelta(days=days)
            return start.timestamp(), (start+timedelta(days=1)).timestamp()
        if re.search(r'за (?:последн\w+ )?(?:неделю|семь дней|7 дней)', lower):
            return (today-timedelta(days=6)).timestamp(), (today+timedelta(days=1)).timestamp()
        return None, None

    def recall(self, binding, query, *, generation=None, exclude_source_ids=(),
               exclude_turn_id=None, paired_source_ids=(), limit=4, is_current=None):
        from .working_memory import excerpt, terms
        self._binding(binding)
        if not isinstance(query, str) or not 1 <= len(query) <= 8000:
            raise ValueError('archive_source_invalid')
        self.expire(binding)
        _current(is_current)
        with self.memory.connect() as db:
            db.execute('BEGIN')
            scope = self._scope(db, binding)
            if not scope['policy']['read_enabled']:
                raise PermissionError('archive_disabled')
            if generation is not None and scope['generation'] != generation:
                raise PermissionError('archive_context_changed')
            generation = scope['generation']
            since, until = self._period(query, scope['policy']['timezone'], self.clock())
            # Remove only date/recap scaffolding, never a concrete topic. A
            # topical query with no match must not become a random day recap.
            normalized=re.sub(r'\b(?:позавчера|вчера|сегодня)(?:шн\w*)?\b',' ',query,flags=re.I)
            recap=bool(re.search(r'\b(?:о ч[её]м|что (?:мы|я)|какие темы|напомни.*(?:разговор|бесед))\b',normalized,re.I))
            if since is not None and recap:
                normalized=re.sub(r'\b(?:напомни|беседовал\w*|говорил\w*|шла|ш[её]л|речь|тем[аыуе]|разговор\w*|бесед[аыуе]|последн\w*|недел\w*|семь|дней|день|был)\b',' ',normalized,flags=re.I)
            query_terms = terms(normalized)-{'дн'}
            clauses = ['s.binding_key=?', "a.namespace='production'", "a.status='completed'", 's.heard=1']
            args = [binding.key]
            if since is not None:
                clauses += ['n.accepted_at>=?', 'n.accepted_at<?']; args += [since, until]
            if exclude_turn_id:
                clauses.append('s.source_turn_id!=?'); args.append(exclude_turn_id)
            where = ' AND '.join(clauses)
            common = ''' FROM native_archive_sources s JOIN messages m ON m.id=s.message_id
                JOIN archive_messages a ON a.message_id=m.id JOIN native_archive_turns n
                ON n.binding_key=s.binding_key AND n.source_turn_id=s.source_turn_id '''
            if query_terms:
                expression = ' OR '.join('"'+word.replace('"','')+'"*' for word in sorted(query_terms)[:16])
                candidates = db.execute('''SELECT s.source_turn_id,bm25(archive_fts) AS rank'''+common+
                    ''' JOIN retrieval_chunks r ON r.message_id=m.id JOIN archive_fts ON archive_fts.rowid=r.id
                    WHERE archive_fts MATCH ? AND '''+where+
                    ' ORDER BY rank,n.accepted_at DESC LIMIT 48', [expression,*args]).fetchall()
            elif since is not None or re.search(r'помни|вспом|(?:последн|прошл).*(?:разговор|вопрос)|что (?:мы|я)', query, re.I):
                candidates = db.execute('SELECT s.source_turn_id'+common+' WHERE '+where+
                    ' GROUP BY s.source_turn_id ORDER BY max(n.accepted_at) DESC LIMIT 24', args).fetchall()
            else:
                candidates = []
            excluded, paired = set(map(str, exclude_source_ids)), set(map(str,paired_source_ids))
            chosen, visited = [], set()
            for candidate in candidates:
                if candidate['source_turn_id'] in visited:
                    continue
                visited.add(candidate['source_turn_id'])
                rows = db.execute('''SELECT m.id,m.role,m.content,m.provider,m.created,s.source_turn_id,s.heard,s.complete,
                    s.provenance,s.aliases,a.topic_id'''+common+
                    ' WHERE '+where+' AND s.source_turn_id=? ORDER BY m.id', [*args,candidate['source_turn_id']]).fetchall()
                question_in_packet=any(row['role']=='user' and
                    ('archive:'+str(row['id']) in paired or set(json.loads(row['aliases'])) & paired) for row in rows)
                rows=[row for row in rows if 'archive:'+str(row['id']) not in excluded and
                      not set(json.loads(row['aliases'])) & excluded]
                # A source that is already known must never be returned again.
                # Keep exchange coupling: no answer without its question in
                # this source packet. A later fresh context can retrieve both.
                if rows and (rows[0]['role']=='user' or question_in_packet):chosen.append(rows)
                if len(chosen) >= max(1,min(6,int(limit))):
                    break
            chosen.sort(key=lambda rows: rows[0]['created'])
            messages, remaining = [], 7000
            for rows in chosen:
                for row in rows:
                    if remaining < 80:
                        break
                    content, shortened = excerpt(row['content'], min(1200,remaining))
                    remaining -= len(content)
                    messages.append({'id':'archive:'+str(row['id']), 'turn_id':row['source_turn_id'],
                        'role':row['role'],'content':content,'provider':row['provider'],'heard':bool(row['heard']),
                        'status':'completed' if row['complete'] else 'incomplete',
                        'content_complete':bool(row['complete']) and not shortened,'excerpted':shortened,
                        'created_at':row['created'],'local_date':datetime.fromtimestamp(row['created'],ZoneInfo(scope['policy']['timezone'])).date().isoformat(),
                        'timezone':scope['policy']['timezone'],'provenance':row['provenance'],
                        'source_kind':'device_archive'})
            # Reuse the existing incremental local source blocks. Every quote
            # is joined back to an allowed, still-present heard source; a block
            # never authorizes another topic, owner, date or stale generation.
            notes=[]
            included={item['id'] for item in messages}
            for topic in dict.fromkeys(row['topic_id'] for rows in chosen for row in rows):
                block=db.execute('''SELECT b.content FROM topic_summaries b JOIN topics t ON t.id=b.topic_id
                    WHERE b.topic_id=? AND b.generation=t.generation ORDER BY b.version DESC LIMIT 1''',(topic,)).fetchone()
                if not block:continue
                try:quotes=json.loads(block['content']).get('source_excerpts',[])
                except (TypeError,ValueError,AttributeError):continue
                for quote in quotes[:6]:
                    if not isinstance(quote,dict) or type(quote.get('id')) is not int:continue
                    source=db.execute('SELECT m.id,m.role,m.content,m.created,s.complete,s.provenance,s.aliases'+common+
                        ' WHERE '+where+' AND m.id=?',[*args,quote['id']]).fetchone()
                    if not source:continue
                    ident='archive:'+str(source['id'])
                    if ident in included or ident in excluded or set(json.loads(source['aliases'])) & excluded:continue
                    if quote.get('role')!=source['role'] or quote.get('excerpt')!=source['content'][:100]:continue
                    notes.append({'id':ident,'role':source['role'],'excerpt':quote['excerpt'],
                        'heard':True,'content_complete':bool(source['complete']) and len(source['content'])<=100,
                        'provenance':source['provenance'],'source_kind':'device_archive',
                        'local_date':datetime.fromtimestamp(source['created'],ZoneInfo(scope['policy']['timezone'])).date().isoformat(),
                        'timezone':scope['policy']['timezone']})
                    included.add(ident)
            from .context_manager import ContextManager,tokens
            def encode_notes():
                return json.dumps({'kind':'attributed_excerpts_not_inferred_decisions',
                    'source_excerpts':notes,'coverage':'partial_saved_source_notes_not_verified_facts'},ensure_ascii=False)
            while notes and tokens(encode_notes())>ContextManager.configured().limits['summary']:notes.pop(0)
            summary=encode_notes() if notes else ''
            summary_ids=[item['id'] for item in notes]
            _current(is_current)
        if not self.current(binding,generation,read=True):
            raise PermissionError('archive_context_changed')
        _current(is_current)
        return {'schema':'native-archive-recall-v1','useful':bool(messages or summary), 'messages':messages,'summary':summary,
                'summary_source_ids':summary_ids,
                'source_ids':[row['id'] for row in messages]+summary_ids, 'context_version':generation,
                'archive_generation':generation,'coverage':'saved_device_conversations_only',
                'lookup_kind':'local_fts_and_source_notes','private_archive_accessed':False,
                'reason':'relevant_archive_sources' if messages or summary else 'no_matching_archive_source'}

    def enqueue(self, binding, operation, *, is_current, **values):
        """Bounded process-local write lane; admission never waits for SQLite.

        The original immutable source and generation travel with the job. A
        timed-out/cancelled thread must recheck its fence before SQL commit.
        """
        if operation not in {'question', 'answer'} or not callable(is_current):
            raise ValueError('archive_source_invalid')
        self._binding(binding)
        if self._closed:
            return False
        if self._writes is None:
            self._writes = asyncio.Queue(maxsize=64)
        try:
            self._writes.put_nowait((binding, operation, values, is_current))
        except asyncio.QueueFull:
            self.last_errors[binding.key] = 'archive_write_queue_full'
            return False
        self.pending_writes[binding.key] = self.pending_writes.get(binding.key,0)+1
        if self._writer is None or self._writer.done():
            self._writer = asyncio.create_task(self._write_loop())
        return True

    async def _write_loop(self):
        while True:
            binding, operation, values, current = await self._writes.get()
            active = [True]
            def permitted(active=active, current=current):
                return active[0] and current()
            try:
                method = self.record_question if operation == 'question' else self.record_answer
                await asyncio.wait_for(asyncio.to_thread(method, binding, is_current=permitted, **values), 2.)
                self.last_errors.pop(binding.key, None)
                await asyncio.wait_for(asyncio.to_thread(self.memory.archive.maintain_one,
                                                        native_binding=binding.key), 1.)
            except asyncio.CancelledError:
                raise
            except (PermissionError, ValueError):
                self.last_errors[binding.key] = 'archive_source_context_changed'
            except TimeoutError:
                self.last_errors[binding.key] = 'archive_write_timeout'
            except Exception:
                self.last_errors[binding.key] = 'archive_write_unavailable'
            finally:
                active[0] = False
                self.pending_writes[binding.key] = max(0,self.pending_writes.get(binding.key,1)-1)
                self._writes.task_done()

    async def wait_idle(self):
        if self._writes is not None:
            await self._writes.join()

    async def close(self, *, grace_seconds=2):
        self._closed = True
        if self._writes is not None and grace_seconds:
            try:
                await asyncio.wait_for(self.wait_idle(),max(0,min(2,float(grace_seconds))))
            except TimeoutError:
                pass
        if self._writer is not None:
            self._writer.cancel()
            await asyncio.gather(self._writer, return_exceptions=True)
            self._writer = None
        if self._writes is not None:
            while not self._writes.empty():
                binding,*_ = self._writes.get_nowait()
                self.pending_writes[binding.key] = max(0,self.pending_writes.get(binding.key,1)-1)
                self._writes.task_done()


@dataclass(frozen=True)
class _StoredBinding:
    """Internal expiry key; never accepted by public read/write operations."""
    key: str
    archive_owner: str
