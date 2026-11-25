"""P0 household fixtures through the real C session, tools and SQLite.

Only external IO is fake: Live sideband, Open-Meteo HTTP, Luna HTTP and the
explicitly granted expert executor. A case's ``expected`` object is never read
by this adapter. Semantic speech/acoustic/device acceptance remains separate.
"""
from __future__ import annotations

import asyncio
import copy
import json
import re
import sqlite3
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from gobot.live import LiveManager
from gobot.live_backend import LiveBackend, MODEL
from gobot.live_contract import LiveCommand
from gobot.owner_testing import OwnerTestPolicy
from gobot.weather import WeatherClient
from test_live import LIVE_SDP, Provider, Socket, offer
from test_realtime_native import configured


PACK = Path(__file__).resolve().parents[1] / 'docs/behavior-library-20261111'
P0_IDS = tuple(
    [f'W{i:03}' for i in (*range(1, 7), *range(11, 22), *range(47, 50), *range(56, 70))]
    + [f'T{i:03}' for i in range(1, 11)]
    + [f'X{i:03}' for i in (1, 2, 6, 7, 8, 9, 10)]
    + [f'C{i:03}' for i in range(1, 6)]
)
CASES = {row['id']: row for row in json.loads((PACK / 'dialogue-cases.json').read_text(encoding='utf-8'))['cases']}
BASE = json.loads((PACK / 'fixtures.json').read_text(encoding='utf-8'))['fixtures'][0]


def merge_fixture(base, override):
    """The package's recursive-object merge; lists replace, never concatenate."""
    if isinstance(base, dict) and isinstance(override, dict):
        return {key: merge_fixture(base.get(key), value) if key in override else copy.deepcopy(value)
                for key, value in {**base, **override}.items()}
    return copy.deepcopy(override)


def stamp(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()


class FakeWeatherHTTP:
    """Provider-shaped source, with synthetic coordinates as stable place IDs."""

    def __init__(self, fixture):
        self.fixture = fixture
        self.requests = []
        self.geocoder_requests = []
        # No real household coordinates are in fixtures or runtime test databases.
        self.coordinates = {key: (float(index), float(index) + .25)
                            for index, key in enumerate(fixture['places'])}
        self.held = None
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.released = False
        self.cancelled = 0

    def place_for(self, latitude, longitude):
        point = (float(latitude), float(longitude))
        return next(key for key, pair in self.coordinates.items() if pair == point)

    def location(self, place_id):
        place = self.fixture['places'][place_id]
        lat, lon = self.coordinates[place_id]
        return {'enabled': True, 'location_name': place['display_name'], 'latitude': lat, 'longitude': lon}

    def geocoding(self, query):
        value = query.casefold().replace('ё', 'е')
        aliases = {'home': ('сан-паулу', 'сан паулу', 'sao paulo'), 'rio': ('рио', 'rio'),
                   'lisbon': ('лиссабон', 'lisbon'), 'moscow': ('москв', 'москва', 'moscow'),
                   'springfield_il': ('иллин', 'illinois'), 'springfield_ma': ('массач', 'massachusetts')}
        if 'спрингфил' in value or 'springfield' in value:
            ids = self.fixture.get('geocoder_candidates', ['springfield_il', 'springfield_ma'])
        else:
            ids = [key for key, words in aliases.items() if any(word in value for word in words)]
        result = []
        for key in ids:
            place = self.fixture['places'][key]
            lat, lon = self.coordinates[key]
            parts = place['display_name'].split(', ', 1)
            result.append({'id': list(self.coordinates).index(key) + 1, 'name': parts[0],
                           'admin1': parts[1] if len(parts) > 1 else '', 'latitude': lat,
                           'longitude': lon, 'timezone': place['timezone']})
        return {'results': result}

    def raw_weather(self, place_id):
        fixture = self.fixture
        source = copy.deepcopy(fixture.get('weather_responses_by_place', {}).get(place_id, fixture['weather_fixture']))
        zone = fixture['places'][place_id]['timezone']
        today = datetime.fromtimestamp(stamp(fixture['clock_utc']), ZoneInfo(zone)).date()
        # Source fixtures specify values; dates must correspond to the requested
        # place's own local day, including fallback synthetic places.
        if place_id not in fixture.get('weather_responses_by_place', {}):
            for index, row in enumerate(source['daily']):
                row['date'] = (today + timedelta(days=index)).isoformat()
        current = source['current']
        daily = source['daily']
        return {
            'timezone': zone,
            'current_units': {'temperature_2m': '°C', 'wind_speed_10m': 'km/h', 'wind_gusts_10m': 'km/h'},
            'current': {'time': stamp(source['fetched_at']), 'temperature_2m': current['temperature_c'],
                        'apparent_temperature': current.get('apparent_temperature_c', current['temperature_c']),
                        'relative_humidity_2m': current.get('relative_humidity_percent', 65),
                        'weather_code': current.get('weather_code', 2), 'wind_speed_10m': current['wind_speed_kmh'],
                        'wind_gusts_10m': current.get('wind_gust_kmh', current['wind_speed_kmh'] + 9),
                        'precipitation': current.get('precipitation_mm', 0)},
            'daily_units': {'temperature_2m_min': '°C', 'temperature_2m_max': '°C',
                            'wind_speed_10m_max': 'km/h', 'wind_gusts_10m_max': 'km/h'},
            'daily': {'time': [row['date'] for row in daily],
                      'weather_code': [row.get('weather_code', 2) for row in daily],
                      'temperature_2m_min': [row['temperature_min_c'] for row in daily],
                      'temperature_2m_max': [row['temperature_max_c'] for row in daily],
                      'precipitation_probability_max': [row['precipitation_probability_percent'] for row in daily],
                      'precipitation_sum': [row.get('precipitation_sum_mm', 0) for row in daily],
                      'wind_speed_10m_max': [row['wind_speed_kmh'] for row in daily],
                      'wind_gusts_10m_max': [row['wind_gust_kmh'] for row in daily],
                      'uv_index_max': [row.get('uv_index', 4) for row in daily]},
        }

    async def __call__(self, request):
        if request.url.host == 'geocoding-api.open-meteo.com':
            assert request.url.path == '/v1/search'
            self.geocoder_requests.append(request)
            return httpx.Response(200, json=self.geocoding(request.url.params['name']))
        assert request.url.host == 'api.open-meteo.com' and request.url.path == '/v1/forecast'
        place = self.place_for(request.url.params['latitude'], request.url.params['longitude'])
        self.requests.append((place, request))
        if self.held is not None and not self.entered.is_set():
            self.entered.set()
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                # A source can finish after the requesting coroutine was cancelled.
                # Delivering it still must not publish a stale result.
                self.cancelled += 1
                await self.release.wait()
            self.released = True
        error = self.fixture.get('weather_error')
        if error == 'timeout':
            raise httpx.ReadTimeout('synthetic source timeout', request=request)
        if error in {'http_503', 'http_429'}:
            return httpx.Response(int(error[5:]), json={'error': 'synthetic'})
        return httpx.Response(200, json=self.raw_weather(place))


class FakeLunaHTTP:
    def __init__(self):
        self.requests = []
        self.output_text = 'Это синтетический ответ внешнего backend. Он не подтверждает выполненных действий.'

    async def __call__(self, request):
        assert request.url.host == 'api.openai.com'
        body = json.loads(request.content)
        self.requests.append((str(request.url.path), body))
        if request.url.path == '/v1/responses/input_tokens':
            return httpx.Response(200, json={'input_tokens': 300})
        assert request.url.path == '/v1/responses'
        events = [{'type': 'response.created', 'response': {'model': MODEL}},
                  {'type': 'response.output_text.delta', 'delta': self.output_text},
                  {'type': 'response.completed', 'response': {'model': MODEL, 'status': 'completed',
                     'usage': {'input_tokens': 300, 'output_tokens': 25, 'total_tokens': 325}}}]
        return httpx.Response(200, text='\n\n'.join('data: ' + json.dumps(row) for row in events) + '\n\n',
                              headers={'content-type': 'text/event-stream'})


class UnknownCloseProvider(Provider):
    """Failed close acknowledgement and failed cleanup; never fake finalization."""
    @asynccontextmanager
    async def attach(self, ident):
        sock = Socket(self.creations[-1])
        original = sock.send

        async def send(raw):
            if json.loads(raw)['type'] == 'session.close':
                sock.sent.append(json.loads(raw))
                # An immediate failed transport is a real error path, avoiding
                # an eight-second fixture sleep without changing runtime timeouts.
                raise ConnectionError('synthetic unconfirmed close')
            await original(raw)
        sock.send = send
        self.sockets.append(sock)
        yield sock

    async def cleanup(self, ident):
        self.cleanup_calls.append(ident)
        raise ConnectionError('synthetic cleanup unavailable')


class FailingTimerConnection:
    """Inject failure at the actual SQLite INSERT, not at the router/tool return."""
    def __init__(self, connection):
        self.context = connection
        self.connection = None
    def __enter__(self):
        self.connection = self.context.__enter__()
        return self
    def __exit__(self, *args):
        return self.context.__exit__(*args)
    def __getattr__(self, name):
        return getattr(self.connection, name)
    def execute(self, sql, *args):
        if re.match(r'\s*INSERT\s+INTO\s+timers\b', sql, re.I):
            raise sqlite3.OperationalError('synthetic timer storage failure')
        return self.connection.execute(sql, *args)


class HouseholdAdapter:
    def __init__(self, tmp_path, settings, monkeypatch, case):
        self.tmp_path, self.settings, self.monkeypatch = tmp_path, settings, monkeypatch
        # Deliberately retain only inputs, never ``expected`` or a desired trace.
        self.case_id = case['id']
        self.turns = copy.deepcopy(case['turns'])
        self.fixture = merge_fixture(BASE, case.get('given_overrides', {}))
        self.clock = stamp(self.fixture['clock_utc'])
        monkeypatch.setattr(time, 'time', lambda: self.clock)
        self.weather_http = FakeWeatherHTTP(self.fixture)
        self.luna_http = FakeLunaHTTP()
        self.provider = UnknownCloseProvider() if any(t['event'] == 'live_close_result' for t in self.turns) else Provider()
        self.manager = None
        self.sessions = []
        self.session = None
        self.profiles = {}
        self.appends, self.events, self.results, self.context_reads, self.profile_writes = [], [], [], [], []
        self.source_results = []
        self.archive_reads = []
        self.timer_aliases = {}
        self.sequence = 0
        self.offsets = {}
        self.background = []
        self.expert_release = asyncio.Event()
        self.expert_entered = asyncio.Event()
        self.expert_calls = []
        self.last_event = None
        self.final_turn_id = None
        self.final_query = ''
        self.mode_reset = False

    async def start(self):
        rt, _, _ = configured(self.tmp_path, self.settings)
        self.manager = LiveManager(rt, provider=self.provider)
        rt.live = self.manager
        self.manager.brain.configuration.weather = WeatherClient(transport=httpx.MockTransport(self.weather_http), clock=lambda: self.clock)
        self.manager.backend = LiveBackend(self.tmp_path / 'mock-luna', rt.owner_testing,
                                          key_loader=lambda: 'synthetic-no-network-key', transport=httpx.MockTransport(self.luna_http))
        devices = self.manager.brain.configuration.devices
        for device in {self.fixture['device_id'], *(t.get('device_id') for t in self.turns if t.get('device_id'))}:
            key = device + '@household-fixture'
            profile = devices.profile(key)
            patch = {'screen': {'automatic_illustrations': False, 'generation_allowed': False, 'generation_consent': False}}
            if self.fixture['home_place_id'] is not None:
                patch['weather'] = self.weather_http.location(self.fixture['home_place_id'])
            profile = devices.update(key, patch)
            self.profiles[device] = (key, profile)
        self._instrument()
        await self.activate(self.fixture['device_id'])
        self.seed_timers()
        self.initial_timers = self.timer_rows()
        self.initial_archive_count = self.archive_count()
        if self.fixture.get('timer_storage_error'):
            original = self.manager.brain.memory.connect
            self.monkeypatch.setattr(self.manager.brain.memory, 'connect', lambda: FailingTimerConnection(original()))
        if self.fixture.get('pending_weather'):
            self.session.weather_topic = True
            self.session.weather_last_request = {'operation': 'weather_current'}

    def _instrument(self):
        brain = self.manager.brain
        original_settings = brain.configuration.execute
        async def settings_execute(req, slots, **kwargs):
            record = {'turn_id': req.turn_id, 'executor': 'settings', 'slots': copy.deepcopy(slots)}
            self.results.append(record)
            result = await original_settings(req, slots, **kwargs)
            record['result'] = result
            return result
        self.monkeypatch.setattr(brain.configuration, 'execute', settings_execute)
        original_tool = brain.tools.execute
        def tool_execute(tool, req, slots=None):
            record = {'turn_id': req.turn_id, 'executor': tool, 'slots': copy.deepcopy(slots or {})}
            self.results.append(record)
            try:
                result = original_tool(tool, req, slots)
            except Exception as error:
                record['error'] = type(error).__name__
                raise
            record['result'] = result
            return result
        self.monkeypatch.setattr(brain.tools, 'execute', tool_execute)
        original_context = brain.memory.context
        def context(req):
            self.context_reads.append({'device': req.device_id, 'client': req.client_id, 'epoch': req.profile_epoch,
                                       'conversation': req.conversation_id})
            return original_context(req)
        self.monkeypatch.setattr(brain.memory, 'context', context)
        original_update = brain.configuration.devices.update
        def update(owner, body):
            before = brain.configuration.devices.profile(owner).model_dump()
            result = original_update(owner, body)
            self.profile_writes.append({'owner': owner, 'before': before, 'after': result.model_dump(), 'patch': copy.deepcopy(body)})
            return result
        self.monkeypatch.setattr(brain.configuration.devices, 'update', update)
        for name in ('search', 'source', 'period'):
            original = getattr(brain.memory.archive, name)
            def read(*args, _name=name, _original=original, **kwargs):
                self.archive_reads.append((_name, args))
                return _original(*args, **kwargs)
            self.monkeypatch.setattr(brain.memory.archive, name, read)
        weather = brain.configuration.weather
        for name in ('current', 'forecast'):
            original = getattr(weather, name)
            async def source(place, *args, _name=name, _original=original, **kwargs):
                result = await _original(place, *args, **kwargs)
                self.source_results.append({'place_id': self.weather_http.place_for(place.latitude, place.longitude),
                                            'method': _name, 'result': copy.deepcopy(result)})
                return result
            self.monkeypatch.setattr(weather, name, source)

    async def activate(self, device):
        # Owner Full Test grants one bound client. Multi-device cases therefore
        # activate sequentially in one Brain/database; separate scope probes
        # exercise another client's lookup while A's opaque state still exists.
        if self.session and not self.session.closed:
            await self.manager.close(self.session.id, self.session.offer.device_id, self.session.offer.client_id,
                                     self.session.offer.profile_epoch, 'fixture_device_switch')
        _, profile = self.profiles[device]
        self.manager.owner_testing.policy_path.write_text(OwnerTestPolicy(
            enabled=True, authorization='synthetic-household-fixture', allowed_client_id=profile.client_id,
            live_enabled=True, live_backend_enabled=True, images_enabled=False,
            device_settings_enabled=self.fixture.get('can_configure_device', True),
        ).model_dump_json(), encoding='utf-8')
        req = offer(conversation_mode='unified').model_copy(update={
            'session_id': f'household-{len(self.sessions) + 1}', 'conversation_id': 'conversation_fixture',
            'device_id': device, 'client_id': profile.client_id, 'profile_epoch': str(self.fixture['profile_epoch']),
        })
        self.session, _ = await self.manager.start(req, profile)
        session = self.session
        self.sessions.append(session)
        original_emit, original_append = session.emit, session.append
        def emit(kind, **data):
            self.events.append({'session_id': session.id, 'turn_id': session.current.id if session.current else None,
                                'type': kind, 'data': copy.deepcopy(data)})
            return original_emit(kind, **data)
        async def append(kind, text, delegation_id=None):
            record = {'session_id': session.id, 'turn_id': session.current.id if session.current else None,
                      'kind': kind, 'text': text, 'delegation_id': delegation_id}
            await original_append(kind, text, delegation_id)
            if not session.closed and not session.closing:
                self.appends.append(record)
        session.emit, session.append = emit, append

    def seed_timers(self):
        with self.manager.brain.memory.connect() as connection:
            for row in self.fixture.get('timers', []):
                profile = self.profiles.get(row['device_id'], (None, None))[1]
                client = profile.client_id if profile else 'inaccessible-household-fixture'
                connection.execute('INSERT INTO timers VALUES(?,?,?,?,?)', (
                    row['id'], 'realtime-device:' + client, self.session.access.context_conversation,
                    stamp(row['deadline_utc']), 'running' if row['status'] == 'active' else row['status']))
                self.timer_aliases[row['id']] = row['id']

    def timer_rows(self):
        with self.manager.brain.memory.connect() as connection:
            return {row['id']: dict(row) for row in connection.execute('SELECT * FROM timers ORDER BY deadline,id')}

    def archive_count(self):
        with self.manager.brain.memory.connect() as connection:
            return connection.execute('SELECT count(*) FROM archive_messages').fetchone()[0]

    async def settle(self):
        session = self.session
        # Background lifetime timers/readers are intentionally excluded.
        checked = set()
        for _ in range(4):
            tasks = [task for task in [session.mode_control_task, *session.delegation_tasks.values(), session.backend_task]
                     if task and task not in checked]
            if not tasks:
                break
            for task in tasks:
                checked.add(task)
                try:
                    await asyncio.wait_for(asyncio.shield(task), 5)
                except asyncio.CancelledError:
                    pass
        if session.closing and not session.closed:
            await self.manager.close(session.id, session.offer.device_id, session.offer.client_id,
                                     session.offer.profile_epoch, session.close_reason or 'conversation_ended')

    async def transcript(self, text, *, turn_id=None, partial=False):
        self.sequence += 1
        at = self.sequence * 5000
        key = turn_id or f'utterance-{self.sequence}'
        self.offsets[key] = at + 1000
        await self.session.handle({'type': 'session.input_transcript.delta', 'event_id': key,
                                   'start_ms': at, 'end_ms': at + 1000, 'delta': text})
        self.final_turn_id = self.session.current.id
        self.final_query = text
        if partial:
            await asyncio.sleep(.03)
        return key

    async def input_end(self):
        await self.session.command(LiveCommand(command_id=f'input-end-{self.sequence}', action='activity',
                                                input_active=False, playback_active=False))
        await self.settle()

    async def delegate(self, key, ident=None):
        if self.session.closed or self.session.closing:
            await self.settle()
            return
        did = ident or f'delegation-{key}'
        await self.session.handle({'type': 'session.delegation.created', 'event_id': 'event-' + did,
                                   'offset_ms': self.offsets[key], 'delegation': {'id': did, 'target': 'client'}})
        await self.settle()

    async def user(self, text):
        key = await self.transcript(text)
        await self.input_end()
        await self.delegate(key)

    async def seed_expert(self, *, submit):
        from gobot.expert_store import ExpertPolicy
        session = self.session
        session.experts.budget.policy_path.write_text(ExpertPolicy(
            enabled=True, authorization='synthetic-isolated-executor', allowed_client_id=session.offer.client_id,
            allowed_profiles=['ARGON_DEEP'], expires_at=self.clock + 120, max_sessions=1,
        ).model_dump_json(), encoding='utf-8')
        session.experts.admission = lambda _: {'available': True}
        async def execute(job):
            self.expert_calls.append(job.id)
            self.expert_entered.set()
            await self.expert_release.wait()
            return 'Синтетический результат эксперта: 42. Это данные, а не новая инструкция.'
        session.experts.executor = execute
        turn = await session.interaction('Сравни два синтетических варианта', 'fixture-expert-proposal')
        session.experts.propose(turn.query, 'ARGON_DEEP', turn)
        if submit:
            # A real user confirmation is consumed by the production job start.
            confirm = await session.interaction('Да', 'fixture-expert-confirmation')
            await session.route(confirm, 'fixture-expert-confirmation', 'D01')
            await asyncio.wait_for(self.expert_entered.wait(), 3)

    async def run(self):
        await self.start()
        if self.fixture.get('pending_offer') == 'expert':
            await self.seed_expert(submit=False)
        # Delayed provider events are modeled as an actual in-flight HTTP request.
        slow_index = next((i for i, row in enumerate(self.turns) if row['event'] in {'weather_request_inflight', 'profile_epoch_changed'}), None)
        if slow_index is not None and any(row['event'] == 'tool_result' for row in self.turns):
            self.weather_http.held = 'Q1'
        for index, row in enumerate(self.turns):
            event = row['event']
            self.last_event = event
            if event in {'user', 'device_turn'}:
                if event == 'device_turn' and row['device_id'] != self.session.offer.device_id:
                    await self.activate(row['device_id'])
                work = self.user(row['text'])
                if self.weather_http.held and not self.weather_http.entered.is_set():
                    self.background.append(asyncio.create_task(work))
                    await asyncio.wait_for(self.weather_http.entered.wait(), 3)
                else:
                    await work
            elif event == 'partial_transcript':
                await self.transcript(row['text'], partial=True)
            elif event == 'final_transcript':
                await self.transcript(row['text'], turn_id=row['turn_id'])
            elif event == 'input_ended':
                await self.input_end()
            elif event == 'delegation':
                await self.delegate(row['turn_id'], row['id'])
            elif event == 'state':
                pending = row.get('pending', {})
                if pending.get('domain') == 'weather':
                    self.session.weather_topic = True
                    # Fixture IDs are not runtime opaque references. Omitting a
                    # place uses the already configured device-home location.
                    self.session.weather_last_request = {'operation': 'weather_forecast'}
                    assert pending.get('place_id', 'home') == 'home'
                else:
                    raise NotImplementedError('fixture state requires an actual authorized runtime state boundary')
            elif event == 'weather_request_inflight':
                assert self.weather_http.entered.is_set()
            elif event == 'tool_result':
                # The result enters through the real WeatherClient HTTP await.
                self.weather_http.release.set()
                outcomes = await asyncio.gather(*self.background, return_exceptions=True)
                for outcome in outcomes:
                    if isinstance(outcome, BaseException) and not isinstance(outcome, asyncio.CancelledError):
                        raise outcome
                await self.settle()
            elif event == 'session_closed':
                await self.manager.close(self.session.id, self.session.offer.device_id, self.session.offer.client_id,
                                         self.session.offer.profile_epoch, 'conversation_ended')
            elif event == 'new_activation':
                await self.activate(self.fixture['device_id'])
            elif event == 'profile_epoch_changed':
                await self.manager.invalidate_principal(self.session.offer.device_id, 'profile_changed')
            elif event == 'assistant':
                # A model utterance is not permission; an actual proposal was
                # already created by the fixture's pending_offer setup.
                assert self.session.experts.pending
            elif event == 'expert_submitted':
                await self.seed_expert(submit=True)
            elif event == 'expert_completed':
                self.expert_release.set()
                await asyncio.wait_for(self.session.experts.pending.worker, 3)
            elif event == 'live_close_result':
                await self.settle()
                assert not self.session.final_usage_confirmed
            elif event == 'mode_state':
                assert row['mode'] == 'A'
                self.manager.modes.select(self.session.mode_flow, 'legacy')
                await self.manager.close(self.session.id, self.session.offer.device_id, self.session.offer.client_id,
                                         self.session.offer.profile_epoch, 'mode_switch')
                self.activation_count_at_idle = len(self.provider.creations)
            elif event == 'playback_ended':
                self.manager.modes.activity(self.session.mode_flow, False, False)
            elif event == 'idle_elapsed':
                flow = self.session.mode_flow
                flow.last_activity = time.monotonic() - row['seconds'] - .01
                self.manager.modes.activity(flow, False, False)
                self.mode_reset = not flow.active and flow.mode == 'live'
            elif event == 'assistant_speaking':
                await self.session.command(LiveCommand(command_id='fixture-speaking', action='activity', input_active=False, playback_active=True))
            else:
                raise NotImplementedError('event adapter missing: ' + event)
        return self.observed()

    async def close(self):
        self.weather_http.release.set()
        self.expert_release.set()
        await asyncio.gather(*self.background, return_exceptions=True)
        if self.manager:
            await self.manager.shutdown()
            await self.manager.realtime.shutdown()

    def alias(self, ident):
        if ident not in self.timer_aliases:
            self.timer_aliases[ident] = f'T{len(self.timer_aliases) + 1:02}'
        return self.timer_aliases[ident]

    def observed(self):
        session = self.session
        rows = self.timer_rows()
        created = [row for ident, row in rows.items() if ident not in self.initial_timers]
        cancelled = [ident for ident, row in rows.items() if row['status'] == 'cancelled' and self.initial_timers.get(ident, {}).get('status') != 'cancelled']
        untouched = [ident for ident, row in self.initial_timers.items() if rows.get(ident) == row]
        for row in created:
            self.alias(row['id'])
        commentaries = [row for row in self.appends if row['kind'] == 'commentary']
        final_comments = [row['text'] for row in commentaries if row['turn_id'] == self.final_turn_id]
        text = ' '.join(final_comments)
        finals = [row for row in self.results if row['turn_id'] == self.final_turn_id]
        delivered = finals[-1] if finals else {}
        result = delivered.get('result')
        evidence = (result.evidence or {}) if result else {}
        frame = getattr(result, 'frame', None) if result else None
        frame = frame.model_dump() if frame else {}
        weather = frame.get('metadata', {}).get('weather') or {}
        weather_request = evidence.get('weather_request', {})
        slots = {}
        missing = evidence.get('missing_slots', [])
        reason = evidence.get('reason')
        if not missing:
            if reason == 'weather_location_ambiguous':
                missing = ['region']
            elif reason in {'weather_location_required', 'weather_location_not_found', 'weather_place_expired'}:
                missing = ['place']
        action = 'unobserved'
        if weather:
            action = 'weather_query'
            place_label = weather.get('place') or frame.get('subtitle')
            ids = [key for key, place in self.fixture['places'].items() if place['display_name'] == place_label]
            if ids:
                slots['place_id'] = ids[0]
            elif self.source_results:
                slots['place_id'] = self.source_results[-1]['place_id']
            slots['period'] = weather.get('kind')
            days = weather.get('days') or []
            if days:
                slots.update(start_date=days[0]['date'], end_date=days[-1]['date'])
            if weather.get('timezone'):
                slots['timezone'] = weather['timezone']
            if weather.get('metric') or weather_request.get('metric'):
                slots['metric'] = weather.get('metric') or weather_request['metric']
        elif result and result.widget and result.widget.get('payload', {}).get('command') == 'timer.start':
            action = 'timer_start'
            slots['duration_seconds'] = result.widget['payload']['duration_ms'] // 1000
        elif evidence.get('timer_cancelled_ids'):
            action = 'timer_cancel'
        elif delivered.get('error'):
            action, reason = 'report_failure', 'storage_error' if delivered['error'] == 'OperationalError' else 'execution_error'
        elif reason:
            action = 'report_failure'
        elif getattr(result, 'setup', None):
            if result.setup.get('status', '').startswith('awaiting'):
                action = 'clarify'
        if result and (evidence.get('abstained') or delivered.get('executor') == 'skill_readiness'):
            if reason and any(suffix in reason for suffix in ('not_implemented', 'not_configured', 'not_connected')):
                action = 'report_unavailable'
            elif delivered.get('slots', {}).get('operation') == 'weather_provider_unavailable':
                action, reason = 'report_unavailable', 'provider_not_configured'
            elif delivered.get('executor') == 'skill_readiness':
                action = 'report_unavailable'
                category = delivered.get('slots', {}).get('category')
                reason = {'music': 'music_not_connected', 'timers_named': 'named_timer_not_implemented', 'timer_named': 'named_timer_not_implemented'}.get(category, reason)
        if result and not weather and ('?' in result.text or delivered.get('executor') == 'quick_clarify' or missing
                                       or result.text.startswith('Сначала попроси показать таймеры')):
            action = 'clarify'
            if not missing:
                if re.search(r'город|мест[оа]|насел[её]н', result.text, re.I):
                    missing = ['region' if len(self.weather_http.geocoder_requests) else 'place']
                elif re.search(r'минут|секунд|длительност', result.text, re.I):
                    missing = ['duration_unit']
                elif re.search(r'уточни|ч[её]м|како[йм]', result.text, re.I):
                    missing = ['domain']
        if delivered.get('slots', {}).get('operation') in {'weather_query_cancel', 'weather_cancel_query'} and result:
            action = 'cancel_pending_weather'
        final_events = [row for row in self.events if row['turn_id'] == self.final_turn_id]
        if any(row['type'] == 'backend_status' and row['data'].get('state') == 'completed' for row in final_events):
            action = 'conversation_answer'
        if any(row['type'] == 'expert_blocked' for row in final_events):
            action, reason = 'report_unavailable', 'expert_admission_unavailable'
        if self.last_event == 'partial_transcript' and not self.weather_http.requests and not finals:
            action = 'wait_input_end'
        if session.closed:
            if session.close_reason == 'profile_changed':
                action = 'discard_stale'
            elif session.close_reason == 'mode_switch' and not session.final_usage_confirmed:
                action = 'mode_switch_pending'
            elif session.close_reason == 'conversation_ended':
                action = 'conversation_end'
        if self.mode_reset:
            action = 'reset_mode_selection'
        if self.fixture.get('pending_offer') == 'expert' and session.experts.pending and session.experts.pending.state == 'cancelled':
            action = 'decline_pending'
        expert_results = [row for row in self.events if row['type'] == 'expert_result']
        if expert_results and self.last_event == 'expert_completed':
            action = 'store_result_card'
        reasons = {'weather_source_timeout': 'source_timeout', 'weather_source_unavailable': 'upstream_unavailable',
                   'weather_provider_rate_limit': 'rate_limited', 'weather_rate_limit': 'rate_limited'}
        reason = reasons.get(reason, reason)
        generations = [body for path, body in self.luna_http.requests if path == '/v1/responses']
        jobs = [job for s in self.sessions for job in s.experts.jobs.values()]
        submitted = [job for job in jobs if job.operation_id or job.call_id]
        source_claims = sum(bool(re.search(r'\d|градус|километр\w* в час|км/ч', row['text'], re.I)) for row in commentaries)
        observed = {
            'action': action, 'slots': slots, 'reason': reason, 'missing_slots': missing,
            'provider_requests': len(self.weather_http.requests), 'geocoder_requests': len(self.weather_http.geocoder_requests),
            'home_mutations': sum(row['before']['weather'] != row['after']['weather'] for row in self.profile_writes),
            'device_mutations': len(self.profile_writes), 'provider_config_mutations': sum('provider' in str(row['patch']) for row in self.profile_writes),
            'clarifications': sum('?' in row['text'] for row in commentaries),
            'timer_create_count': len(created), 'timer_cancel_count': len(cancelled),
            'cancelled_timer_ids': [self.alias(ident) for ident in cancelled], 'untouched_timer_ids': [self.alias(ident) for ident in untouched],
            'active_timer_ids': [self.alias(ident) for ident, row in rows.items() if row['status'] == 'running' and row['deadline'] > self.clock and row['device_id'] == 'realtime-device:' + session.offer.client_id],
            'confirmation_requests': sum(bool(re.search(r'подтвер|разреш', row['text'], re.I)) and '?' in row['text'] for row in commentaries),
            'confirmation_count': sum('Таймер запущен' in row['text'] for row in commentaries),
            'final_answer_count': len(final_comments), 'success_claims': sum('Таймер запущен' in row['text'] for row in commentaries),
            'numeric_weather_claims': source_claims, 'retry_count': max(0, len(self.weather_http.requests) - 1),
            'expert_job_count': len(submitted), 'expert_start_count': len(self.expert_calls),
            'awaiting_confirmation_jobs': sum(job.state == 'awaiting_confirmation' for job in jobs),
            'expert_cancel_count': sum(job.state == 'cancelled' for job in submitted),
            'mode': 'A' if session.mode_flow.public()['mode'] == 'legacy' else 'C',
            'selected_mode': 'A' if session.mode_flow.public()['mode'] == 'legacy' else 'C',
            'live_connected': not session.closed, 'conversation_closed': session.closed,
            'claimed_mode_A': any(row['type'] == 'closed' and row['data'].get('final_usage_confirmed') and row['data'].get('mode', {}).get('mode') == 'legacy' for row in self.events),
            'live_new_connection_count': len(self.provider.creations) - getattr(self, 'activation_count_at_idle', len(self.provider.creations)),
            'private_context_reads': len(self.archive_reads) + sum(row['device'].startswith('personal:') for row in self.context_reads),
            'private_context_transfers': sum('private_fixture' in json.dumps(config) for config in self.provider.creations[1:]),
            'cross_device_context_reads': sum(row['client'] == self.session.offer.client_id and row['device'] == self.fixture['device_id'] for row in self.context_reads) if self.session.offer.device_id != self.fixture['device_id'] else 0,
            'semantic_memory_writes': self.archive_count() - self.initial_archive_count,
            'second_function_call_output_count': sum(event.get('item', {}).get('type') == 'function_call_output' for sock in self.provider.sockets for event in sock.sent),
            'stale_voice_interruptions': sum(not row['data'].get('voice_deferred', False) for row in expert_results),
            'card_storage': 'session_ram' if expert_results and all(not job.remember for job in jobs) else None,
            'stale_results_spoken': sum(row['turn_id'] != self.final_turn_id and re.search(r'Open-Meteo', row['text']) is not None for row in commentaries) if self.weather_http.held else 0,
            'luna_action_claims': len(generations),
            'playback_start_count': sum(row['executor'] in {'music', 'media_playback'} and
                                        bool(row.get('result') and (row['result'].evidence or {}).get('verified'))
                                        for row in self.results),
        }
        if generations:
            body = generations[-1]
            with self.manager.backend.connect() as connection:
                counts = [row[0] for row in connection.execute('SELECT counted_input FROM calls WHERE counted_input IS NOT NULL')]
            observed.update(luna_input_tokens=max(counts), luna_output_token_limit=body.get('max_output_tokens'),
                            luna_tools_count=len(body.get('tools', [])), luna_retries=max(0, len(generations) - 1),
                            full_catalogue_in_prompt=len(body.get('input', '')) > 50000 or '"scenario_count":400' in body.get('input', '').replace(' ', ''))
        # A speech field is observed only if its value reached a real tool result
        # and the corresponding named quantity is in that result's spoken text.
        speech_fields = []
        if weather and result:
            spoken = text.casefold()
            values = weather.get('days', [{}])[0] if weather.get('days') else frame.get('metadata', {}).get('facts', {})
            if ('low' in values or 'temperature_min' in values) and re.search(r'температур|от .+ до|градус', spoken):
                speech_fields += ['temperature_min', 'temperature_max']
            if re.search(r'вероятност|осадк', spoken) and any(key in values for key in ('rain_percent', 'precipitation_probability')):
                speech_fields += ['precipitation_probability']
            if 'ветер' in spoken and any(key in values for key in ('wind_kmh', 'wind_speed')):
                speech_fields += ['wind_speed']
            if 'порыв' in spoken and any(key in values for key in ('gust_kmh', 'wind_gust_kmh', 'wind_gust')):
                speech_fields += ['wind_gust']
            if re.search(r'км/ч|километр', spoken):
                speech_fields += ['unit']
        if slots.get('metric') == 'wind':
            speech_fields = [field for field in ('wind_speed', 'wind_gust', 'unit') if field in speech_fields]
        elif slots.get('metric') == 'temperature':
            speech_fields = [field for field in ('temperature_min', 'temperature_max') if field in speech_fields]
        else:
            speech_fields = [field for field in ('temperature_min', 'temperature_max', 'precipitation_probability', 'wind_speed') if field in speech_fields]
        observed['speech_fields'] = speech_fields
        return observed

