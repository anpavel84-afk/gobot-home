"""Owner settings for the already enrolled Sophia column.

The browser never chooses a principal, profile row, device ID, coordinates or
provider URL. Reads use the existing DeviceStore database without creating a
profile. Weather setup follows SettingsTools' find -> explicit choice -> source
verification -> save/readback sequence, with a revision fence for web editors.

Only weather settings are writable here. Voice grants, firmware, household
history, credentials and model selection are deliberately outside this schema.
"""
import asyncio
import hashlib
import inspect
import json
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import time

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from .device_contract import DeviceProfile, WeatherPreferences
from .realtime_api import bounded_json
from .weather import WeatherClient, WeatherError


PREFIX = '/api/sophia/admin'
NO_STORE = {'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'}
APPLICATION = {
    'status': 'next_weather_request',
    'message': ('Сохранённый город читается погодным инструментом при следующем запросе. '
                'Обновление подсказки активного голосового сеанса подтверждается отдельно.'),
    'device_acknowledged': False,
}
SAFE_WEATHER_ERRORS = {
    'weather_rate_limit', 'weather_source_timeout', 'weather_provider_rate_limit',
    'weather_source_unavailable', 'weather_source_rejected', 'weather_invalid_data',
    'weather_response_limit', 'weather_data_not_fresh', 'location_query_invalid',
}


def _digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _safe_weather(weather):
    if isinstance(weather, WeatherPreferences):
        weather = weather.model_dump()
    return {key: weather[key] for key in ('enabled', 'provider', 'location_name')}


def _fail(status, code):
    raise HTTPException(status, code)


class SophiaAdmin:
    """One existing column, short-lived verified places, atomic profile edits."""

    CANDIDATE_SECONDS = 600
    VERIFICATION_SECONDS = 300
    MAX_PENDING = 128

    def __init__(self, root, *, weather_client=None, clock=time.time):
        self.root = Path(root)
        self.db = self.root/'data/browser-devices/profiles.sqlite'
        self.config = self.root/'data/hardware/gobot-v1/gateway.json'
        self.weather = weather_client if weather_client is not None else WeatherClient()
        self.clock = clock
        self.lock = threading.RLock()
        self.verification_lock = asyncio.Lock()
        self.candidates = {}
        self.verifications = {}
        self.checks = {}

    def _paths(self):
        # Missing storage is an operational problem, never a reason to enroll a
        # browser profile or silently create a replacement column configuration.
        if (not self.db.is_file() or self.db.is_symlink() or self.db.parent.is_symlink()
                or not self.config.is_file() or self.config.is_symlink()):
            _fail(503, 'admin_profile_unavailable')

    def _target(self):
        self._paths()
        try:
            config = json.loads(self.config.read_text(encoding='utf-8'))
            target = config['device_id']
            if (not isinstance(target, str) or not re.fullmatch(r'spotpear-[a-f0-9]{12}', target)
                    or config.get('client_id', target) != target):
                raise ValueError()
            return target
        except (OSError, ValueError, KeyError, TypeError):
            _fail(503, 'admin_target_unavailable')

    def _connect(self, *, write=False):
        self._paths()
        # mode=rw also refuses creation on the explicit write path.
        connection = sqlite3.connect(self.db.resolve().as_uri()+('?mode=rw' if write else '?mode=ro'),
                                     uri=True, timeout=3)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _existing(db, target):
        prefix = target+'@'
        rows = db.execute('SELECT owner,profile FROM profiles WHERE substr(owner,1,?)=?',
                          (len(prefix), prefix)).fetchall()
        matches = []
        for row in rows:
            profile = DeviceProfile.model_validate_json(row['profile'])
            if profile.client_id == target and profile.client_kind == 'spotpear':
                matches.append((row['owner'], row['profile'], profile))
        if len(matches) != 1:
            _fail(503, 'admin_profile_ambiguous' if matches else 'admin_profile_unavailable')
        owner, raw, profile = matches[0]
        return {'target': target, 'owner': owner, 'raw': raw, 'profile': profile,
                'revision': _digest(raw)}

    def read(self):
        try:
            target = self._target()
            with self._connect() as db:
                return self._existing(db, target)
        except (sqlite3.Error, OSError, ValueError, TypeError):
            _fail(503, 'admin_profile_unavailable')

    def _expire(self):
        now = self.clock()
        for values in (self.candidates, self.verifications, self.checks):
            for key in [key for key, value in values.items() if value['expires_at'] <= now]:
                del values[key]

    def _remember(self, collection, key, value):
        self._expire()
        if len(collection) >= self.MAX_PENDING:
            del collection[next(iter(collection))]
        collection[key] = value

    @staticmethod
    def _actor(actor):
        if not isinstance(actor, str) or not actor or len(actor) > 512:
            _fail(403, 'admin_owner_required')
        return _digest('sophia-admin-owner\0'+actor)

    def _public(self, record):
        with self.lock:
            self._expire()
            check = self.checks.get(record['target'])
            if check and check['revision'] != record['revision']:
                check = None
            check = self._check_public(check) if check else None
        weather = record['profile'].weather
        home_context = {'weather_location_configured': weather.enabled,
                        'weather_location': weather.location_name if weather.enabled else None,
                        'location_basis': 'configured_device_home_not_live_gps'}
        return {
            'ok': True, 'observed_at': self.clock(),
            'target': {'id': record['target'], 'label': 'Spotpear · София', 'kind': 'spotpear'},
            'revision': record['revision'],
            'settings': {'weather': _safe_weather(weather)},
            'supported_fields': ['weather.enabled', 'weather.location'],
            'application': {**APPLICATION, 'expected_home_context_revision': _digest(_canonical(home_context))},
            'weather_check': check,
        }

    def settings(self):
        return self._public(self.read())

    @staticmethod
    def _check_public(value):
        keys = ('verified', 'checked_at', 'expires_at', 'duration_ms', 'data_age_seconds',
                'provider', 'reason_code')
        return {key: value[key] for key in keys if key in value}

    def changes(self, actor, *, record=None):
        actor_hash = self._actor(actor)
        record = record or self.read()
        try:
            with self._connect() as db:
                present = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='sophia_admin_operations'").fetchone()
                if not present:
                    return []
                rows = db.execute('SELECT * FROM sophia_admin_operations WHERE target=? AND actor_hash=? '
                                  'ORDER BY at DESC, rowid DESC LIMIT 50', (record['target'], actor_hash)).fetchall()
                return [self._change(row) for row in rows]
        except (sqlite3.Error, ValueError, TypeError):
            _fail(503, 'admin_history_unavailable')

    @staticmethod
    def _change(row):
        return {'id': row['operation_id'], 'at': row['at'], 'before': json.loads(row['before_weather']),
                'after': json.loads(row['after_weather']), 'revision': row['revision'],
                'application': dict(APPLICATION)}

    async def locations(self, actor, body):
        actor_hash = self._actor(actor)
        if not isinstance(body, dict) or set(body) != {'query'}:
            _fail(422, 'invalid_weather_query')
        query = body['query']
        if (not isinstance(query, str) or not 2 <= len(query.strip()) <= 100
                or any(ord(char) < 32 for char in query)):
            _fail(422, 'invalid_weather_query')
        record = await asyncio.to_thread(self.read)
        try:
            places = await self.weather.locations(query.strip())
        except WeatherError as error:
            code = str(error) if str(error) in SAFE_WEATHER_ERRORS else 'weather_source_unavailable'
            _fail(503, code)
        # Do not return coordinates, raw provider data, search URLs or keys.
        candidates = []
        with self.lock:
            expires = self.clock()+self.CANDIDATE_SECONDS
            for place in places[:3]:
                try:
                    valid = WeatherPreferences(**place, enabled=True)
                except (TypeError, ValueError):
                    _fail(503, 'weather_invalid_data')
                ident = secrets.token_hex(16)
                self._remember(self.candidates, ident, {
                    'actor_hash': actor_hash, 'target': record['target'],
                    'revision': record['revision'], 'place': valid,
                    'expires_at': expires,
                })
                candidates.append({'id': ident, 'location_name': valid.location_name})
        return {'ok': True, 'candidates': candidates, 'expires_at': expires, 'revision': record['revision']}

    def _candidate(self, actor_hash, record, ident):
        self._expire()
        if not isinstance(ident, str) or not re.fullmatch('[a-f0-9]{32}', ident):
            _fail(422, 'invalid_weather_candidate')
        value = self.candidates.get(ident)
        if not value or value['actor_hash'] != actor_hash or value['target'] != record['target']:
            _fail(410, 'weather_candidate_expired')
        if value['revision'] != record['revision']:
            _fail(409, 'revision_conflict')
        return value['place']

    async def verify(self, actor, body):
        # A later failed check must not be overtaken by an earlier slow success.
        # This lock is per already-enrolled column, not a global provider queue.
        async with self.verification_lock:
            return await self._verify(actor, body)

    async def _verify(self, actor, body):
        actor_hash = self._actor(actor)
        if not isinstance(body, dict) or set(body)-{'candidate_id'}:
            _fail(422, 'invalid_weather_verification')
        candidate_id = body.get('candidate_id')
        record = await asyncio.to_thread(self.read)
        with self.lock:
            if candidate_id is not None:
                place = self._candidate(actor_hash, record, candidate_id)
            else:
                # A disabled configured location can be checked before enabling.
                try:
                    place = WeatherPreferences(**{**record['profile'].weather.model_dump(), 'enabled': True})
                except ValueError:
                    _fail(422, 'weather_location_required')
            # A new explicit check replaces the actor's previous proof for this
            # candidate even when the source will fail. An old green badge is
            # not permission to save after a known later failed source check.
            for ident in [ident for ident, value in self.verifications.items()
                          if value['actor_hash'] == actor_hash and value['target'] == record['target']
                          and value['candidate_id'] == candidate_id]:
                del self.verifications[ident]
            if candidate_id is None:
                self.checks.pop(record['target'], None)
        start = time.monotonic()
        try:
            result = await self.weather.current(place)
        except WeatherError as error:
            code = str(error) if str(error) in SAFE_WEATHER_ERRORS else 'weather_source_unavailable'
            if candidate_id is None:
                with self.lock:
                    self._remember(self.checks, record['target'], {
                        'revision': record['revision'], 'verified': False, 'checked_at': self.clock(),
                        'expires_at': self.clock()+self.VERIFICATION_SECONDS,
                        'duration_ms': round((time.monotonic()-start)*1000),
                        'provider': 'open_meteo', 'reason_code': code,
                    })
            _fail(503, code)
        after = await asyncio.to_thread(self.read)
        if after['target'] != record['target'] or after['revision'] != record['revision']:
            _fail(409, 'revision_conflict')
        now = self.clock()
        expires = now+self.VERIFICATION_SECONDS
        if candidate_id is not None:
            with self.lock:
                self._candidate(actor_hash, after, candidate_id)
                expires = min(expires, self.candidates[candidate_id]['expires_at'])
        check = {'verified': True, 'checked_at': now, 'expires_at': expires,
                 'duration_ms': round((time.monotonic()-start)*1000),
                 'data_age_seconds': max(0, round(now-result['observed_at'])), 'provider': 'open_meteo'}
        ident = secrets.token_hex(16)
        with self.lock:
            self._remember(self.verifications, ident, {
                **check, 'actor_hash': actor_hash, 'target': record['target'],
                'revision': record['revision'], 'candidate_id': candidate_id, 'place': place,
            })
            if candidate_id is None:
                self._remember(self.checks, record['target'], {**check, 'revision': record['revision']})
        return {'ok': True, **check, 'verification_id': ident, 'candidate_id': candidate_id,
                'location_name': place.location_name}

    @staticmethod
    def _body(body, *, apply=False):
        fields = {'expected_revision', 'patch'} | ({'operation_id'} if apply else set())
        if not isinstance(body, dict) or set(body) != fields:
            _fail(422, 'invalid_setting')
        revision = body['expected_revision']
        patch = body['patch']
        if (not isinstance(revision, str) or not re.fullmatch('[a-f0-9]{64}', revision)
                or not isinstance(patch, dict) or set(patch) != {'weather'}
                or not isinstance(patch['weather'], dict) or not patch['weather']
                or set(patch['weather'])-{'enabled', 'candidate_id', 'verification_id'}):
            _fail(422, 'invalid_setting')
        weather = patch['weather']
        if 'enabled' in weather and type(weather['enabled']) is not bool:
            _fail(422, 'invalid_setting')
        for key in ('candidate_id', 'verification_id'):
            if key in weather and (not isinstance(weather[key], str)
                                  or not re.fullmatch('[a-f0-9]{32}', weather[key])):
                _fail(422, 'invalid_setting')
        if apply and (not isinstance(body['operation_id'], str)
                      or not re.fullmatch('[A-Za-z0-9_-]{16,80}', body['operation_id'])):
            _fail(422, 'invalid_operation_id')
        return weather

    def _proposed(self, actor_hash, record, body):
        if body['expected_revision'] != record['revision']:
            _fail(409, 'revision_conflict')
        patch = body['patch']['weather']
        current = record['profile'].weather
        enabled = patch.get('enabled', current.enabled)
        candidate_id = patch.get('candidate_id')
        if candidate_id is not None:
            proposed = self._candidate(actor_hash, record, candidate_id)
            if not enabled:
                _fail(422, 'weather_choice_requires_enabled')
        else:
            try:
                proposed = WeatherPreferences(**{**current.model_dump(), 'enabled': enabled})
            except ValueError:
                _fail(422, 'weather_location_required')
        changed = proposed != current
        # Changing the confirmed place or enabling weather needs fresh proof.
        # Leaving an unchanged enabled profile does not trigger a provider call.
        if candidate_id is not None or (enabled and not current.enabled):
            self._expire()
            verification = self.verifications.get(patch.get('verification_id'))
            if (not verification or verification['actor_hash'] != actor_hash
                    or verification['target'] != record['target']):
                _fail(410, 'verification_expired')
            if verification['revision'] != record['revision']:
                _fail(409, 'revision_conflict')
            if verification['candidate_id'] != candidate_id or verification['place'] != proposed:
                _fail(422, 'weather_verification_mismatch')
        changes = []
        for field in ('enabled', 'location_name'):
            before, after = getattr(current, field), getattr(proposed, field)
            if before != after:
                changes.append({'field': 'weather.'+field, 'before': before, 'after': after})
        return proposed, changed, changes

    def validate(self, actor, body):
        actor_hash = self._actor(actor)
        self._body(body)
        record = self.read()
        with self.lock:
            proposed, changed, changes = self._proposed(actor_hash, record, body)
        return {'ok': True, 'revision': record['revision'], 'changes': changes,
                'unchanged': not changed, 'weather': _safe_weather(proposed),
                'application': dict(APPLICATION)}

    @staticmethod
    def _operation_table(db):
        # Same transaction/database as the existing profile: the idempotency
        # receipt cannot claim success without the corresponding saved values.
        db.execute('CREATE TABLE IF NOT EXISTS sophia_admin_operations ('
                   'operation_id TEXT PRIMARY KEY, actor_hash TEXT NOT NULL, target TEXT NOT NULL, '
                   'request_hash TEXT NOT NULL, prior_revision TEXT NOT NULL, revision TEXT NOT NULL, '
                   'before_weather TEXT NOT NULL, after_weather TEXT NOT NULL, at REAL NOT NULL)')

    def apply(self, actor, body):
        actor_hash = self._actor(actor)
        self._body(body, apply=True)
        request_hash = _digest(_canonical(body))
        target = self._target()
        try:
            with self.lock, self._connect(write=True) as db:
                db.execute('BEGIN IMMEDIATE')
                record = self._existing(db, target)
                present = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='sophia_admin_operations'").fetchone()
                previous = (db.execute('SELECT * FROM sophia_admin_operations WHERE operation_id=?',
                                       (body['operation_id'],)).fetchone() if present else None)
                if previous:
                    if (previous['actor_hash'] != actor_hash or previous['target'] != target
                            or previous['request_hash'] != request_hash):
                        _fail(409, 'operation_conflict')
                    return {'ok': True, 'operation_id': body['operation_id'], 'idempotent': True,
                            'unchanged': False, 'settings': self._public(record), 'change': self._change(previous)}
                proposed, changed, _ = self._proposed(actor_hash, record, body)
                if not changed:
                    return {'ok': True, 'operation_id': body['operation_id'], 'idempotent': False,
                            'unchanged': True, 'settings': self._public(record), 'change': None}
                updated = record['profile'].model_copy(update={'weather': proposed})
                # Full existing DeviceProfile validation preserves its identity
                # and all fields that are outside this route's tiny patch schema.
                updated = DeviceProfile.model_validate(updated.model_dump())
                raw = updated.model_dump_json()
                revision = _digest(raw)
                before = _safe_weather(record['profile'].weather)
                after = _safe_weather(proposed)
                at = self.clock()
                self._operation_table(db)
                result = db.execute('UPDATE profiles SET profile=? WHERE owner=? AND profile=?',
                                    (raw, record['owner'], record['raw']))
                if result.rowcount != 1:
                    _fail(409, 'revision_conflict')
                db.execute('INSERT INTO sophia_admin_operations VALUES(?,?,?,?,?,?,?,?,?)', (
                    body['operation_id'], actor_hash, target, request_hash, record['revision'], revision,
                    _canonical(before), _canonical(after), at))
                saved = self._existing(db, target)
                if saved['profile'] != updated or saved['revision'] != revision:
                    _fail(503, 'admin_settings_readback_failed')
                # Explicit commit before a success receipt or proof reassignment.
                db.commit()
                proof = self.verifications.get(body['patch']['weather'].get('verification_id'))
                if proof and proof.get('place') == proposed and proof.get('revision') == record['revision']:
                    self._remember(self.checks, target, {**self._check_public(proof), 'revision': revision})
                else:
                    self.checks.pop(target, None)
                change = {'id': body['operation_id'], 'at': at, 'before': before, 'after': after,
                          'revision': revision, 'application': dict(APPLICATION)}
                return {'ok': True, 'operation_id': body['operation_id'], 'idempotent': False,
                        'unchanged': False, 'settings': self._public(saved), 'change': change}
        except (sqlite3.Error, OSError, ValueError, TypeError):
            _fail(503, 'admin_settings_unavailable')


def attach_sophia_admin(app, root, *, authenticate, runtime_status=None, weather_client=None, clock=time.time):
    """Mount on the existing private application; caller supplies owner auth.

    ``authenticate(request, write=False)`` returns a stable verified owner
    identity. Guest browser binding and expense authority are not sufficient.
    ``runtime_status()`` is an optional async redacted existing status reader.
    """
    service = SophiaAdmin(root, weather_client=weather_client, clock=clock)

    async def owner(request, *, write=False):
        actor = authenticate(request, write=write)
        if inspect.isawaitable(actor):
            actor = await actor
        service._actor(actor)
        return actor

    def response(value):
        return JSONResponse(value, headers=NO_STORE)

    @app.get(PREFIX+'/settings')
    async def settings(request: Request):
        await owner(request)
        return response(await asyncio.to_thread(service.settings))

    @app.get(PREFIX+'/snapshot')
    @app.get(PREFIX+'/overview')
    async def snapshot(request: Request):
        actor = await owner(request)
        record = await asyncio.to_thread(service.read)
        result = service._public(record)
        result['changes'] = await asyncio.to_thread(service.changes, actor, record=record)
        try:
            runtime = runtime_status() if runtime_status else {'status': 'unknown'}
            if inspect.isawaitable(runtime):
                runtime = await runtime
            result['runtime'] = runtime
        except Exception:
            result['runtime'] = {'status': 'unavailable', 'code': 'runtime_status_unavailable'}
        return response(result)

    @app.get(PREFIX+'/changes')
    async def changes(request: Request):
        actor = await owner(request)
        return response({'ok': True, 'changes': await asyncio.to_thread(service.changes, actor)})

    @app.post(PREFIX+'/weather/locations')
    async def locations(request: Request):
        actor = await owner(request, write=True)
        body = await bounded_json(request, 2048)
        return response(await service.locations(actor, body))

    @app.post(PREFIX+'/weather/verify')
    async def verify(request: Request):
        actor = await owner(request, write=True)
        body = await bounded_json(request, 2048)
        return response(await service.verify(actor, body))

    @app.post(PREFIX+'/settings/validate')
    async def validate(request: Request):
        actor = await owner(request, write=True)
        body = await bounded_json(request, 4096)
        return response(await asyncio.to_thread(service.validate, actor, body))

    @app.post(PREFIX+'/settings/apply')
    async def apply(request: Request):
        actor = await owner(request, write=True)
        body = await bounded_json(request, 4096)
        return response(await asyncio.to_thread(service.apply, actor, body))

    return service
