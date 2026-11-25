"""Scoped working dialogue, grounded summaries and local relevance retrieval.

The source of truth remains Memory.transient. The optional encrypted checkpoint
extends only a server-authorized working scope, not personal archive access.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib
import json
import math
import re
import sqlite3
import time


DEFAULT_TTL = 3600
MAX_TTL = 86400
MAX_ROWS = 256
MAX_SCOPE_ROWS = 128
MAX_ANSWER_CHARACTERS = 64000
FIELDS = ('goals', 'conditions', 'decisions', 'open_questions', 'facts')
TERMINAL = frozenset({'completed', 'cancelled', 'incomplete', 'error'})
_STOP = frozenset('''а и или но в во на по из к у о об обо со с за для при до от
то это этот эта эти того того эту такой какая какой какие как что чего чем где
когда почему зачем кто кого мне меня мной мы вы ты я он она оно они его ее их
мой моя мои твой наш ваши свой такой также уже еще теперь сейчас тогда сегодня
вчера просто пожалуйста расскажи скажи спросил спрашивал вопрос ответ ответь
говорили говорил говорила говорим обсуждали обсуждал обсуждала обсудим помнишь
помню помнит вспомни вспомнить память памяти про нас вам вас будет было были
есть быть хочу можешь может можно да нет ну вот ли бы же ведь подробно подробнее
нужно надо давай рассказывать рассказывай какой-нибудь любой самое снова'''.split())
_ENDING = re.compile(r'(иями|ями|ами|ого|ему|ому|ыми|ими|ов|ев|ам|ям|ах|ях|ом|ем|ая|яя|ую|юю|ые|ие|ий|ый|ой|а|я|ы|и|е|у|ю|о|ь)$')
_RECALL = re.compile(r'помни|вспом|что\s+(?:мы|я|вы|ты).{0,35}(?:говор|обсуж|спраш|реш|выбра)|(?:прошл|предыдущ).{0,20}(?:разговор|бесед)', re.I)
_QUESTION = re.compile(r'^\s*(?:что|чем|чего|как|почему|зачем|где|куда|откуда|когда|кто|сколько|како\w*|можно\s+ли|нужно\s+ли|расскажи|объясни|подскажи)\b', re.I)


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, separators=(',', ':'),
                                     sort_keys=True).encode('utf8')).hexdigest()


def terms(text):
    result = set()
    for word in re.findall(r'[\w]+', str(text).lower().replace('ё', 'е'), re.UNICODE):
        if word in _STOP or len(word) < 2:
            continue
        if re.match(r'^(?:помн|вспом|обсужд|расскаж|спраш)', word):
            continue
        if len(word) > 4 and re.fullmatch(r'[а-я]+', word):
            word = _ENDING.sub('', word)
        if len(word) >= 2:
            result.add(word)
    return result


def excerpt(text, limit):
    if len(text) <= limit:
        return text, False
    marker = ' … [середина сокращена] … '
    available = max(2, limit - len(marker))
    first = (available * 2) // 3
    return text[:first] + marker + text[-(available-first):], True


def scope_key(req):
    return req.device_id, req.conversation_id, req.profile_epoch


def row_key(row):
    return row['owner'], row['conversation'], row.get('epoch')


def source_message(turn_id, row, role):
    content = row['text'] if role == 'user' else row.get('result', '')
    ident = 'wm_' + digest([row['owner'], row['conversation'], row.get('epoch'), turn_id, role, content])[:24]
    return {'id': ident, 'turn_id': turn_id, 'role': role, 'content': content,
            'provider': 'input' if role == 'user' else row.get('provider', ''),
            'heard': True if role == 'user' else bool(row.get('heard', row['status'] == 'completed')),
            'status': row['status'],
            'content_complete': not row.get('result_excerpted', False) and
                                (role == 'user' or row['status'] == 'completed')}


class WorkingMemory:
    def __init__(self, memory, *, protect=None, unprotect=None):
        from .working_memory_store import WorkingMemoryStore
        self.memory = memory
        self.store = WorkingMemoryStore(memory, protect=protect, unprotect=unprotect)
        self.policies = {}
        self.versions = {}
        self.summaries = {}
        self.persistence = {}
        self._term_cache = {}
        self._next_store_cleanup = 0.

    def ttl(self, key):
        return self.policies.get(key, {}).get('ttl_seconds', DEFAULT_TTL)

    def version(self, key):
        return self.versions.get(key, 0)

    def scope_id(self, key):
        return self.policies.get(key, {}).get('scope_id', digest([*key, 'ram_only']))

    def has_checkpoint(self, req):
        return self.store.has_checkpoint(binding_id=digest(scope_key(req)))

    def _rows(self, key, *, exclude_turn=None):
        now = time.time()
        result = [(ident, row) for ident, row in self.memory.transient.items()
                  if ident != exclude_turn and row_key(row) == key and
                  row.get('status') in TERMINAL and now - row['updated'] < self.ttl(key) and
                  row.get('provider') not in {'mock', 'bridge:mock'}]
        return sorted(result, key=lambda item: (item[1]['updated'], item[1].get('sequence', 0)))

    def _messages(self, rows):
        result = []
        for ident, row in rows:
            if row.get('text'):
                result.append(source_message(ident, row, 'user'))
            if row.get('result') and row.get('heard', row['status'] == 'completed'):
                result.append(source_message(ident, row, 'assistant'))
        return result

    def _source_map(self, key):
        return {message['id']: message for message in self._messages(self._rows(key))}

    def prune_locked(self):
        now = time.time()
        if now >= self._next_store_cleanup:
            self._next_store_cleanup = now + 60
            try:
                self.store.purge()
            except sqlite3.Error:
                # Logical expiry is enforced below even if disk cleanup is busy.
                self.store.last_error = 'checkpoint_expiry_cleanup_unavailable'
        changed = set()
        for ident, row in list(self.memory.transient.items()):
            if now - row['updated'] >= self.ttl(row_key(row)):
                changed.add(row_key(row))
                self.memory.transient.pop(ident, None)
                self._term_cache.pop(ident, None)
        for key in changed:
            self.versions[key] = self.version(key) + 1
            self._prune_summary_locked(key)
            self._checkpoint_locked(key)

    def make_room_locked(self, req):
        self.prune_locked()
        key = scope_key(req)
        scoped = [(ident, row) for ident, row in self.memory.transient.items() if row_key(row) == key]
        while len(self.memory.transient) >= MAX_ROWS or len(scoped) >= MAX_SCOPE_ROWS:
            pool = scoped if len(scoped) >= MAX_SCOPE_ROWS else list(self.memory.transient.items())
            pool = [(ident, row) for ident, row in pool if row['status'] != 'running']
            if not pool:
                return False
            ident, removed = min(pool, key=lambda item: item[1]['updated'])
            removed_key = row_key(removed)
            self.memory.transient.pop(ident, None)
            self._term_cache.pop(ident, None)
            self.versions[removed_key] = self.version(removed_key) + 1
            self._prune_summary_locked(removed_key)
            if removed_key != key:
                self._checkpoint_locked(removed_key)
            scoped = [(ident, row) for ident, row in self.memory.transient.items() if row_key(row) == key]
        return True

    def _prune_summary_locked(self, key):
        previous = self.summaries.get(key)
        if not previous:
            return
        sources = self._source_map(key)
        for name in FIELDS:
            previous[name] = [item for item in previous.get(name, [])
                              if set(item['source_ids']) <= sources.keys()]
        previous['source_ids'] = list(dict.fromkeys(
            ident for name in FIELDS for item in previous.get(name, []) for ident in item['source_ids']))
        if not previous['source_ids']:
            self.summaries.pop(key, None)

    def configure(self, req, *, ttl_seconds=43200, persist=True, authorization):
        if req.remember:
            raise ValueError('working_memory_requires_temporary_request')
        if not isinstance(authorization, str) or not authorization.strip():
            raise ValueError('working_memory_requires_server_authorization')
        if isinstance(ttl_seconds, bool) or not DEFAULT_TTL <= int(ttl_seconds) <= MAX_TTL:
            raise ValueError('working_memory_ttl_out_of_range')
        key = scope_key(req)
        auth_digest = digest(authorization)
        policy = {'ttl_seconds': int(ttl_seconds), 'persist': bool(persist),
                  'authorization_digest': auth_digest, 'binding_id': digest(key),
                  'scope_id': digest([*key, auth_digest])}
        with self.memory.transient_lock:
            self.prune_locked()
            previous = self.policies.get(key)
            if previous == policy:
                self.prune_locked()
                return self.status(req)
            if previous and previous['authorization_digest'] != auth_digest:
                self.clear(req, disable=True)
            self.policies[key] = policy
            self.persistence.setdefault(key, {'persisted': False, 'restored_exchanges': 0, 'error': None})
            if previous is None and persist:
                payload = self.store.load(policy['scope_id'], policy['binding_id'], auth_digest)
                if payload:
                    self._restore_locked(key, payload)
                    self.persistence[key].update(persisted=True, error=None)
                elif self.store.last_error:
                    self.persistence[key]['error'] = self.store.last_error
            elif not persist:
                self.store.purge(binding_id=policy['binding_id'])
                self.persistence[key].update(persisted=False, error=None)
            self.prune_locked()
            if self._rows(key):
                self._checkpoint_locked(key)
            return self.status(req)

    def _restore_locked(self, key, payload):
        rows = payload.get('rows', [])
        if not isinstance(rows, list) or len(rows) > MAX_SCOPE_ROWS:
            return
        restored = 0
        now = time.time()
        for item in rows:
            if not isinstance(item, dict) or not isinstance(item.get('turn_id'), str):
                continue
            row = item.get('row')
            if (not isinstance(row, dict) or not {'owner', 'conversation', 'request_hash'} <= row.keys() or row_key(row) != key or
                    row.get('status') not in TERMINAL | {'running'} or
                    not isinstance(row.get('updated'), (float, int)) or
                    not math.isfinite(row['updated']) or row['updated'] > now + 60 or now - row['updated'] >= self.ttl(key) or
                    not isinstance(row.get('text'), str) or not isinstance(row.get('result', ''), str)):
                continue
            if len(self.memory.transient) >= MAX_ROWS:
                break
            ident = item['turn_id']
            if ident in self.memory.transient:
                continue
            row['keys'] = set(value for value in row.get('keys', []) if isinstance(value, str))
            if row['status'] == 'running':
                row.update(status='cancelled', result='', heard=False)
            row['trace'] = '[]'
            row.pop('visual', None)
            self.memory.transient[ident] = row
            restored += 1
        previous_version = payload.get('version', 0)
        if not isinstance(previous_version, int) or not 0 <= previous_version < 2**63:
            previous_version = 0
        self.versions[key] = max(self.version(key), previous_version) + 1
        summary = payload.get('summary')
        if isinstance(summary, dict):
            self.summaries[key] = summary
            try:
                self._prune_summary_locked(key)
            except (KeyError, TypeError):
                self.summaries.pop(key, None)
        self.persistence[key]['restored_exchanges'] = restored

    def changed(self, req):
        with self.memory.transient_lock:
            key = scope_key(req)
            self.versions[key] = self.version(key) + 1
            self._prune_summary_locked(key)
            self._checkpoint_locked(key)

    def _checkpoint_locked(self, key):
        policy = self.policies.get(key)
        if not policy or not policy['persist']:
            return
        rows = [(ident, row) for ident, row in self.memory.transient.items()
                if row_key(row) == key and time.time() - row['updated'] < self.ttl(key)]
        if not rows:
            try:
                self.store.purge(scope_id=policy['scope_id'])
                self.persistence[key].update(persisted=False, error=None)
            except sqlite3.Error:
                self.persistence[key].update(persisted=False, error='checkpoint_expiry_cleanup_unavailable')
            return
        expires = max(row['updated'] for _, row in rows) + self.ttl(key)
        safe = []
        for ident, row in rows[-MAX_SCOPE_ROWS:]:
            fields = ('owner', 'conversation', 'epoch', 'text', 'request_hash', 'status', 'result',
                      'provider', 'updated', 'heard', 'result_excerpted', 'sequence')
            safe.append({'turn_id': ident, 'row': {**{field: row[field] for field in fields if field in row},
                                                   'keys': sorted(row.get('keys', set()))}})
        payload = {'schema': 1, 'scope_id': policy['scope_id'], 'version': self.version(key),
                   'expires': expires, 'rows': safe, 'summary': self.summaries.get(key)}
        success = self.store.save(policy['scope_id'], policy['binding_id'], policy['authorization_digest'], payload, expires)
        self.persistence[key].update(persisted=success, error=self.store.last_error)

    def clear(self, req, *, disable=False):
        with self.memory.transient_lock:
            key = scope_key(req)
            for ident, row in list(self.memory.transient.items()):
                if row_key(row) == key:
                    self.memory.transient.pop(ident, None)
                    self._term_cache.pop(ident, None)
            self.summaries.pop(key, None)
            self.memory.transient_pending.pop(key, None)
            self.versions[key] = self.version(key) + 1
            self.store.purge(binding_id=digest(key))
            self.persistence[key] = {'persisted': False, 'restored_exchanges': 0, 'error': None}
            if disable:
                self.policies.pop(key, None)
            return self.status(req)

    def purge_expired(self):
        with self.memory.transient_lock:
            self._next_store_cleanup = 0.
            self.prune_locked()

    def status(self, req):
        with self.memory.transient_lock:
            self.prune_locked()
            key = scope_key(req)
            rows = self._rows(key)
            policy = self.policies.get(key)
            summary = self.summaries.get(key)
            return {'enabled': bool(policy), 'scope_id': self.scope_id(key),
                    'version': self.version(key), 'ttl_seconds': self.ttl(key),
                    'source_count': len(self._messages(rows)), 'available_exchanges': len(rows),
                    'completed_exchanges': sum(row['status'] == 'completed' for _, row in rows),
                    'persistence_requested': bool(policy and policy['persist']),
                    **self.persistence.get(key, {'persisted': False, 'restored_exchanges': 0, 'error': None}),
                    'summary_kind': 'grounded_semantic_working_summary' if summary else 'attributed_working_sources',
                    'coverage': 'scoped_partial_working_memory',
                    'expires': max((row['updated'] for _, row in rows), default=time.time()) + self.ttl(key)}

    def _summary(self, key, rows, *, excluded=(), query=''):
        excluded = set(excluded)
        sources = {message['id']: message for message in self._messages(rows)}
        allowed = sources.keys() - excluded
        if not allowed:
            return '', []
        query_terms = terms(query)
        previous = self.summaries.get(key, {})
        result = {'kind': 'working_context_v1', 'coverage': 'partial_scoped_working_memory'}
        ranked = []
        for name in FIELDS:
            for item in previous.get(name, []):
                ids = set(item['source_ids'])
                if ids and ids <= allowed:
                    ranked.append((len(terms(item['text']) & query_terms), name, deepcopy(item)))
        ranked.sort(key=lambda entry: entry[0], reverse=True)
        # Entries preserve quotes and attribution; do not invent decisions from excerpts.
        for _, name, item in ranked[:8]:
            result.setdefault(name, []).append(item)
        notes = [message for message in sources.values() if message['id'] in allowed]
        positions = {ident: index for index, ident in enumerate(sources)}
        notes.sort(key=lambda message: (len(terms(excerpt(message['content'], 8000)[0]) & query_terms),
                                        positions[message['id']]), reverse=True)
        result['source_excerpts'] = []
        used = {ident for name in FIELDS for item in result.get(name, []) for ident in item['source_ids']}
        for message in notes:
            if message['id'] in used:
                continue
            quote, short = excerpt(message['content'], 180)
            result['source_excerpts'].append({'id': message['id'], 'source_ids': [message['id']],
                                              'role': message['role'], 'quote': quote,
                                              'heard': message['heard'], 'status': message['status'],
                                              'excerpted': short})
            if len(result['source_excerpts']) >= 4:
                break
        from .context_manager import tokens
        def encoded():
            return json.dumps(result, ensure_ascii=False, separators=(',', ':'))
        while tokens(encoded()) > 480:
            if result['source_excerpts']:
                result['source_excerpts'].pop()
            else:
                removable = [name for name in reversed(FIELDS) if result.get(name)]
                if not removable:
                    return '', []
                result[removable[0]].pop()
        source_ids = list(dict.fromkeys(
            [ident for name in FIELDS for item in result.get(name, []) for ident in item['source_ids']] +
            [item['id'] for item in result['source_excerpts']]))
        return (encoded(), source_ids) if source_ids else ('', [])

    def context(self, req):
        with self.memory.transient_lock:
            self.prune_locked()
            key = scope_key(req)
            rows = self._rows(key, exclude_turn=req.turn_id)
            messages = self._messages(rows[-6:])
            message_ids = [message['id'] for message in messages]
            summary, summary_ids = self._summary(key, rows, excluded=message_ids, query=req.text)
            pending = self.memory.transient_pending.get(key)
            if pending and pending['expires'] <= time.time():
                pending = None
            metadata = self.status(req)
            metadata.update(source_ids=message_ids + summary_ids, summary_source_ids=summary_ids,
                            available_exchanges=len(rows), replay_exchanges=min(6, len(rows)))
            return {'messages': messages, 'summary': summary, 'summary_sources': summary_ids,
                    'facts': [], 'original_question': '',
                    'pending_action': deepcopy(pending) if pending else None,
                    '_memory_meta': metadata}

    def recall(self, req, *, limit=4, exclude_source_ids=()):
        with self.memory.transient_lock:
            self.prune_locked()
            key = scope_key(req)
            rows = self._rows(key, exclude_turn=req.turn_id)
            excluded = set(exclude_source_ids)
            query = terms(req.text)
            explicit = bool(_RECALL.search(req.text))
            candidate_terms = {}
            for ident, row in rows:
                visible = [m for m in self._messages([(ident, row)]) if m['id'] not in excluded]
                if visible:
                    revision = tuple(message['id'] for message in visible)
                    cached = self._term_cache.get(ident)
                    if cached is None or cached[0] != revision:
                        cached = (revision, terms(' '.join(excerpt(message['content'], 8000)[0] for message in visible)))
                        self._term_cache[ident] = cached
                    candidate_terms[ident] = set(cached[1])
            for name in FIELDS:
                for note in self.summaries.get(key, {}).get(name, []):
                    for ident, row in rows:
                        if ident not in candidate_terms:
                            continue
                        ids = {message['id'] for message in self._messages([(ident, row)])}
                        if ids & set(note['source_ids']):
                            candidate_terms[ident] |= terms(note['text'])
            frequency = Counter(term for value in candidate_terms.values() for term in value)
            scored = []
            for ident, row in rows:
                if ident not in candidate_terms:
                    continue
                shared = candidate_terms[ident] & query
                score = sum(1 + math.log((len(candidate_terms) + 1) / (frequency[term] + 1)) for term in shared)
                if score or (explicit and not query):
                    scored.append((score, row['updated'], ident, row))
            chosen = sorted(scored, key=lambda item: (item[0], item[1]), reverse=True)[:max(1, min(6, int(limit)))]
            chosen.sort(key=lambda item: item[1])
            messages, matches, remaining = [], [], 7000
            for score, _, ident, row in chosen:
                current_ids = []
                for message in self._messages([(ident, row)]):
                    if message['id'] in excluded or remaining < 80:
                        continue
                    value = dict(message)
                    value['content'], shortened = excerpt(value['content'], min(1200, remaining))
                    value['content_complete'] = value['content_complete'] and not shortened
                    value['excerpted'] = shortened
                    remaining -= len(value['content'])
                    messages.append(value)
                    current_ids.append(value['id'])
                if current_ids:
                    matches.append({'turn_id': ident, 'score': round(score, 3), 'source_ids': current_ids})
            summary, summary_ids = self._summary(key, [(ident, row) for _, _, ident, row in chosen],
                                                excluded=excluded, query=req.text)
            ids = list(dict.fromkeys([message['id'] for message in messages] + summary_ids))
            return {'schema': 'working-memory-recall-v1', 'status': 'matched' if ids else 'not_found',
                    'useful': bool(ids), 'messages': messages, 'summary': summary,
                    'source_ids': ids, 'context_version': self.version(key),
                    'coverage': 'scoped_partial_working_memory', 'matches': matches,
                    'reason': 'relevant_prior_context' if ids else 'no_relevant_context',
                    'lookup_kind': 'local_lexical_and_grounded_summary', 'private_archive_accessed': False}

    def summary_snapshot(self, req, *, max_messages=16):
        with self.memory.transient_lock:
            self.prune_locked()
            key = scope_key(req)
            rows = self._rows(key)
            all_sources = self._messages(rows)
            previous = deepcopy(self.summaries.get(key))
            limit = max(2, min(32, int(max_messages)))
            sources = all_sources[-limit:]
            if previous and len(all_sources) > limit:
                # Keep a few still-grounded older task anchors in the model's
                # incremental window so a new answer can resolve an old question.
                recent = all_sources[-max(2, limit-4):]
                recent_ids = {item['id'] for item in recent}
                pool = {item['id']: item for item in all_sources}
                anchors = []
                for name in ('open_questions', 'goals', 'conditions', 'decisions', 'facts'):
                    for note in previous.get(name, []):
                        for ident in note['source_ids']:
                            if ident in pool and ident not in recent_ids and ident not in {item['id'] for item in anchors}:
                                anchors.append(pool[ident])
                sources = anchors[:max(0, limit-len(recent))] + recent
            return {'enabled': key in self.policies, 'scope_id': self.scope_id(key),
                    'version': self.version(key), 'generation': self.version(key),
                    'expires': max((row['updated'] for _, row in rows), default=time.time()) + self.ttl(key),
                    'ttl_seconds': self.ttl(key), 'sources': sources,
                    'source_ids': [message['id'] for message in sources], 'previous_summary': previous,
                    'summary_source_ids': previous.get('source_ids', []) if previous else [],
                    'completed_turns': sum(row['status'] == 'completed' for _, row in rows)}

    def apply_summary(self, req, summary, *, source_version=None, source_ids=None,
                      complete_source_ids=None):
        with self.memory.transient_lock:
            self.prune_locked()
            key = scope_key(req)
            if (key not in self.policies or not isinstance(summary, dict) or
                    source_version is None or source_version != self.version(key)):
                return False
            sources = self._source_map(key)
            permitted = set(sources) if source_ids is None else set(source_ids) & sources.keys()
            if not permitted:
                return False
            if complete_source_ids is None:
                replaced = permitted  # Existing callers supplied complete sources.
            else:
                if (not isinstance(complete_source_ids, (list, tuple, set, frozenset)) or
                        not all(isinstance(ident, str) for ident in complete_source_ids) or
                        not set(complete_source_ids) <= permitted):
                    return False
                replaced = set(complete_source_ids)
            accepted = {}
            for name in FIELDS:
                items = summary.get(name, [])
                if not isinstance(items, list) or len(items) > 8:
                    return False
                accepted[name] = []
                for item in items:
                    if not isinstance(item, dict):
                        return False
                    text, quote, ids = item.get('text'), item.get('source_quote'), item.get('source_ids')
                    if (not isinstance(text, str) or not text.strip() or len(text) > 500 or
                            not isinstance(quote, str) or not quote.strip() or len(quote) > 500 or
                            not isinstance(ids, list) or not 1 <= len(ids) <= 4 or
                            not all(isinstance(ident, str) for ident in ids) or not set(ids) <= permitted):
                        return False
                    grounding = [sources[ident] for ident in ids if quote in sources[ident]['content']]
                    if not grounding:
                        return False
                    user_sources = [message for message in grounding if message['role'] == 'user']
                    if name == 'decisions' and not user_sources:
                        return False
                    if name == 'decisions' and not re.search(r'решил|решила|решаем|выбира|соглас|давай|будем|сделаем|подтвержд|оставляем', quote, re.I):
                        return False
                    # New numeric claims cannot be manufactured by compression.
                    numbers = set(re.findall(r'\d+(?:[.,]\d+)?', text))
                    if not numbers <= set(re.findall(r'\d+(?:[.,]\d+)?', ' '.join(sources[ident]['content'] for ident in ids))):
                        return False
                    if not set(re.findall(r'\d+(?:[.,]\d+)?', quote)) <= numbers:
                        return False
                    negative = r'\b(?:не|нет|нельзя|без|никогда)\b|отказ|запрещ|исключ'
                    if re.search(negative, quote, re.I) and not re.search(negative, text, re.I):
                        return False
                    uncertainty = r'возможно|вероятно|кажется|предполага|не уверен|может быть'
                    if re.search(uncertainty, quote, re.I) and not re.search(uncertainty, text, re.I):
                        return False
                    role = 'user' if user_sources else 'assistant'
                    question = '?' in quote or bool(_QUESTION.search(quote))
                    if role == 'user' and question and name in {'facts', 'decisions'}:
                        return False
                    provenance = ('user_question' if role == 'user' and question else
                                  'user_statement' if role == 'user' else 'assistant_statement')
                    accepted[name].append({'text': text.strip(), 'source_ids': list(dict.fromkeys(ids)),
                                           'source_quote': quote, 'provenance': provenance})
            if not any(accepted.values()):
                return False
            previous = self.summaries.get(key, {})
            for name in FIELDS:
                new_text = {item['text'].casefold() for item in accepted[name]}
                retained = [deepcopy(item) for item in previous.get(name, [])
                            if set(item['source_ids']) <= sources.keys() and
                            not set(item['source_ids']) & replaced and item['text'].casefold() not in new_text]
                accepted[name] = (retained + accepted[name])[-8:]
            accepted.update(kind='grounded_semantic_working_summary',
                            coverage='partial_model_interpretation_with_source_quotes',
                            topic=str(summary.get('topic', ''))[:200], updated=time.time())
            accepted['source_ids'] = list(dict.fromkeys(
                ident for name in FIELDS for item in accepted[name] for ident in item['source_ids']))
            self.summaries[key] = accepted
            self.versions[key] = self.version(key) + 1
            self._checkpoint_locked(key)
            return True
