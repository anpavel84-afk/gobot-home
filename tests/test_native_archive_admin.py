"""Real offline owner routes and SQLite receipts; no provider/model transport."""
import asyncio
from copy import deepcopy
import hashlib
import json
import sqlite3
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from gobot.device_contract import DeviceProfile
from gobot.device_store import DeviceStore
from gobot.memory import Memory
from gobot.realtime_ws_api import attach_brain_direct_voice
from gobot.sophia_admin import SophiaAdmin
from gobot.sophia_admin_access import safe_archive_status, safe_runtime_status
from gobot.sophia_panel import attach_sophia_panel


BOARD = 'spotpear-001122aabbcc'
OTHER = 'spotpear-112233bbccdd'
OWNER = 'owner@example.invalid'
TOKEN = 'fixture-archive-token-never-export'
LOCAL = 'http://127.0.0.1:18811'
TAILNET = 'https://plan.tailffc57c.ts.net'
PATH = '/api/v1/voice-ws/archive'
ADMIN = '/api/sophia/admin/archive'
SCOPE = {'source': 'device', 'device_id': BOARD, 'client_id': BOARD}
AUTH = {'Authorization': 'Bearer '+TOKEN}
ORIGIN = {'Origin': LOCAL}
POLICY = {'write_enabled': True, 'read_enabled': True, 'retention_days': 0,
          'timezone': 'America/Sao_Paulo'}


class NoProvider:
    def __getattr__(self, name):
        raise AssertionError('Archive administration must not touch a provider: '+name)


class RecordingTransport(httpx.AsyncBaseTransport):
    def __init__(self, app, calls, failure):
        self.transport = httpx.ASGITransport(app=app)
        self.calls, self.failure = calls, failure

    async def handle_async_request(self, request):
        self.calls.append(request)
        response = await self.transport.handle_async_request(request)
        if request.method == 'POST' and self.failure.pop('lose_reply', False):
            raise httpx.ReadTimeout('PRIVATE_HTTP_CANARY', request=request)
        return response


@pytest.fixture
def fixture(tmp_path):
    config = tmp_path/'data/hardware/gobot-v1'
    config.mkdir(parents=True)
    (config/'gateway.json').write_text(json.dumps({'device_id': BOARD,
        'unified_voice': {'enabled': True}}))
    (tmp_path/'run').mkdir()
    (tmp_path/'run/keys.json').write_text(json.dumps({'api_token': TOKEN}))
    (tmp_path/'data/sophia-admin-owner.json').write_text(json.dumps({
        'version': 1, 'owner_login_sha256': hashlib.sha256(OWNER.encode()).hexdigest(),
        'local_owner_enabled': True}))
    devices = DeviceStore(tmp_path/'data/browser-devices')
    profile = DeviceProfile(client_id=BOARD, client_kind='spotpear')
    with sqlite3.connect(devices.db) as db:
        db.execute('INSERT INTO profiles VALUES(?,?)', (BOARD+'@guest', profile.model_dump_json()))
        db.execute('INSERT INTO profiles VALUES(?,?)',
                   ('personal:other@phone', DeviceProfile().model_dump_json()))
    memory = Memory(str(tmp_path/'data/gobot.sqlite'))
    manager = SimpleNamespace(brain=SimpleNamespace(memory=memory), sessions={}, provider=NoProvider())
    app = FastAPI()

    async def auth(request: Request):
        if request.headers.get('authorization') != 'Bearer '+TOKEN:
            raise HTTPException(401)

    attach_brain_direct_voice(app, SimpleNamespace(sessions={}), manager, auth, TOKEN)
    calls, failure = [], {}
    panel = FastAPI()
    attach_sophia_panel(panel, tmp_path, client_factory=lambda **options:
        httpx.AsyncClient(transport=RecordingTransport(app, calls, failure), **options))
    admin = SophiaAdmin(tmp_path)
    binding, _ = admin.archive_binding()
    return SimpleNamespace(root=tmp_path, app=app, panel=panel, manager=manager,
        memory=memory, service=memory.native_archive, devices=devices, profile=profile,
        admin=admin, binding=binding, calls=calls, failure=failure)


def configure(revision=0, *, operation='archive-configure-0001', values=None):
    return {'action': 'configure', 'values': deepcopy(POLICY if values is None else values),
            'expected_revision': revision, 'operation_id': operation}


def clear(revision, *, operation='archive-clear-000001'):
    return {'action': 'clear', 'confirm': True, 'expected_revision': revision,
            'operation_id': operation}


def assert_private(value):
    text = json.dumps(value, ensure_ascii=False)
    for canary in ('HOUSEHOLD_CANARY', 'PRIVATE_HTTP_CANARY', 'PRIVATE_SOURCE_CANARY',
                   'personal:other', TOKEN, BOARD+'@guest'):
        assert canary not in text


def test_projection_keeps_metadata_and_drops_transcript_topic_labels_and_identifiers():
    state = {'available': True, 'policy': POLICY, 'revision': 4, 'generation': 6,
        'counts': {'turns': 2, 'messages': 4, 'topics': 1, 'blocks': 1, 'backlog': 0,
                   'title': 'HOUSEHOLD_CANARY'},
        'oldest_at': 100, 'newest_at': 200, 'last_write_at': 200, 'last_error': None,
        'storage': 'sqlite_plaintext_windows_acl', 'coverage': 'since_enabled',
        'private_archive': False, 'sources': ['PRIVATE_SOURCE_CANARY'],
        'owner_id': BOARD+'@guest', 'text': 'HOUSEHOLD_CANARY',
        'operation': {'id': 'archive-operation-001', 'applied_revision': 4,
                      'replayed': True, 'text': 'HOUSEHOLD_CANARY'}}
    projected = safe_archive_status(state)
    assert projected['counts'] == {key: state['counts'][key] for key in
                                   ('turns', 'messages', 'topics', 'blocks', 'backlog')}
    assert projected['policy'] == POLICY
    assert projected['operation'] == {'id': 'archive-operation-001',
                                     'applied_revision': 4, 'replayed': True}
    assert_private(projected)


def test_projection_rejects_wrong_types_unbounded_numbers_and_arbitrary_errors():
    result = safe_archive_status({'available': 'yes', 'policy': {**POLICY, 'owner': 'HOUSEHOLD_CANARY'},
        'revision': True, 'generation': 10**1000,
        'counts': {'turns': True, 'messages': -1, 'topics': float('inf'), 'blocks': 10**1000},
        'oldest_at': float('nan'), 'newest_at': 10**1000, 'last_write_at': [],
        'last_error': 'HOUSEHOLD_CANARY', 'operation': {'id': 'HOUSEHOLD_CANARY'}})
    assert result == {'policy': {}, 'counts': {}, 'last_error': 'archive_unavailable', 'operation': None}


def test_runtime_projection_does_not_publish_archive_sources_or_future_receipts():
    archive = {'available': True, 'policy': POLICY, 'revision': 1, 'generation': 1,
        'counts': {'topics': 1}, 'messages': ['HOUSEHOLD_CANARY'],
        'binding': {'owner': BOARD+'@guest'},
        'operation': {'id': 'archive-operation-001', 'applied_revision': 2, 'replayed': True}}
    result = safe_runtime_status({'brain': {'sessions': [{'lifecycle': {'native_archive': archive}}]}},
                                 observed_at=10, gateway_observed_at=None)
    projected = result['brain']['sessions'][0]['lifecycle']['native_archive']
    assert projected['counts'] == {'topics': 1} and projected['operation'] is None
    assert_private(result)


def test_offline_status_is_disabled_without_creating_archive_scope_or_device_profile(fixture):
    with sqlite3.connect(fixture.devices.db) as db:
        before = list(db.execute('SELECT * FROM profiles ORDER BY owner'))
    with TestClient(fixture.panel, base_url=LOCAL, client=('127.0.0.1', 50000)) as client:
        result = client.get(ADMIN)
    assert result.status_code == 200
    state = result.json()['archive']
    assert state['available'] is True and state['revision'] == state['generation'] == 0
    assert state['policy'] == {'write_enabled': False, 'read_enabled': False,
                               'retention_days': 0, 'timezone': 'UTC'}
    assert state['counts']['turns'] == 0 and state['private_archive'] is False
    assert 'no-store' in result.headers['cache-control']
    with fixture.memory.connect() as db:
        assert db.execute('SELECT count(*) FROM native_archive_scopes').fetchone()[0] == 0
    with sqlite3.connect(fixture.devices.db) as db:
        assert list(db.execute('SELECT * FROM profiles ORDER BY owner')) == before
    assert not fixture.manager.sessions
    assert dict(fixture.calls[0].url.params) == SCOPE
    assert_private(result.json())


def test_configure_offline_has_atomic_receipt_and_independent_read_write_switches(fixture):
    with TestClient(fixture.panel, base_url=LOCAL, client=('127.0.0.1', 50000)) as client:
        result = client.post(ADMIN, headers=ORIGIN, json=configure())
        assert result.status_code == 200
        value = result.json()
        assert value['accepted'] is True
        assert value['archive']['policy'] == POLICY
        assert value['archive']['read_effective'] is True
        assert value['archive']['revision'] == value['archive']['generation'] == 1
        receipt = value['archive']['operation']
        assert receipt == {'id': configure()['operation_id'], 'applied_revision': 1, 'replayed': False}
        read = client.get(ADMIN, params={'operation_id': receipt['id']})
        assert read.json()['archive']['operation'] == {**receipt, 'replayed': True}
        disabled = client.post(ADMIN, headers=ORIGIN, json=configure(1,
            operation='archive-disable-0001', values={**POLICY, 'write_enabled': False}))
        assert disabled.status_code == 200
        assert disabled.json()['archive']['policy']['read_enabled'] is True
        assert disabled.json()['archive']['policy']['write_enabled'] is False
    assert not fixture.manager.sessions
    assert_private(value)


def test_memory_skill_only_blocks_lookup_and_leaves_retention_and_recording(fixture):
    fixture.profile.conversation.skills.memory = False
    with sqlite3.connect(fixture.devices.db) as db:
        db.execute('UPDATE profiles SET profile=? WHERE owner=?',
                   (fixture.profile.model_dump_json(), BOARD+'@guest'))
    with TestClient(fixture.panel, base_url=LOCAL, client=('127.0.0.1', 50000)) as client:
        value = client.post(ADMIN, headers=ORIGIN, json=configure()).json()['archive']
    assert value['policy'] == POLICY
    assert value['read_effective'] is False and value['lookup_blocked_by_skill'] is True


def test_revision_conflict_does_not_overwrite_and_operation_replay_cannot_clear_newer_generation(fixture):
    with TestClient(fixture.panel, base_url=LOCAL, client=('127.0.0.1', 50000)) as client:
        assert client.post(ADMIN, headers=ORIGIN, json=configure()).status_code == 200
        stale = client.post(ADMIN, headers=ORIGIN, json=configure(0, operation='archive-stale-000001'))
        assert stale.status_code == 409 and stale.json()['detail'] == 'archive_revision_conflict'
        body = clear(1)
        first = client.post(ADMIN, headers=ORIGIN, json=body)
        assert first.json()['archive']['revision'] == 2
        changed = client.post(ADMIN, headers=ORIGIN, json=configure(2,
            operation='archive-newer-000001', values={**POLICY, 'retention_days': 30}))
        assert changed.json()['archive']['revision'] == 3
        replay = client.post(ADMIN, headers=ORIGIN, json=body)
        assert replay.status_code == 200
        state = replay.json()['archive']
        assert state['generation'] == state['revision'] == 3
        assert state['policy']['retention_days'] == 30
        assert state['operation'] == {'id': body['operation_id'], 'applied_revision': 2, 'replayed': True}
        reused = client.post(ADMIN, headers=ORIGIN, json=clear(3, operation=body['operation_id']))
        assert reused.status_code == 409 and reused.json()['detail'] == 'archive_operation_conflict'


@pytest.mark.parametrize('patch', [
    {'device_id': OTHER}, {'client_id': BOARD}, {'owner_id': 'personal:other'},
    {'source': 'browser'}, {'namespace': 'family:home'}, {'actor_id': '0'*64},
    {'expected_revision': True}, {'expected_revision': -1}, {'operation_id': 'short'},
    {'values': {**POLICY, 'write_enabled': 1}}, {'values': {**POLICY, 'retention_days': True}},
    {'values': {**POLICY, 'retention_days': 36501}}, {'values': {**POLICY, 'timezone': '../outside'}},
])
def test_browser_cannot_choose_scope_identity_or_invalid_policy(fixture, patch):
    with TestClient(fixture.panel, base_url=LOCAL, client=('127.0.0.1', 50000)) as client:
        result = client.post(ADMIN, headers=ORIGIN, json={**configure(), **patch})
    assert result.status_code == 422
    assert not fixture.calls
    assert fixture.service.policy(fixture.binding)['revision'] == 0


def test_clear_needs_true_confirmation_and_get_rejects_principal_and_duplicate_operations(fixture):
    with TestClient(fixture.panel, base_url=LOCAL, client=('127.0.0.1', 50000)) as client:
        for value in (False, 1, 'true', None):
            assert client.post(ADMIN, headers=ORIGIN, json={**clear(0), 'confirm': value}).status_code == 422
        assert client.get(ADMIN, params={'owner_id': 'personal:other'}).status_code == 422
        assert client.get(ADMIN+'?operation_id=archive-a-0000001&operation_id=archive-b-0000001').status_code == 422
    assert not fixture.calls


def test_owner_host_origin_and_tailnet_identity_are_required_before_backend(fixture):
    with TestClient(fixture.panel, base_url=LOCAL, client=('127.0.0.1', 50000)) as client:
        assert client.post(ADMIN, json=configure()).status_code == 403
        assert client.post(ADMIN, headers={'Origin': 'https://foreign.invalid'}, json=configure()).status_code == 403
        assert client.get(ADMIN, headers={'Host': 'foreign.invalid'}).status_code == 403
        assert client.get(ADMIN, headers={'X-Forwarded-Host': 'localhost:18811'}).status_code == 403
    with TestClient(fixture.panel, base_url=TAILNET, client=('127.0.0.1', 50000)) as client:
        assert client.get(ADMIN, headers={'Tailscale-User-Login': 'guest@example.invalid'}).status_code == 403
        assert not fixture.calls
        assert client.get(ADMIN, headers={'Tailscale-User-Login': OWNER}).status_code == 200
    assert len(fixture.calls) == 1


@pytest.mark.parametrize('scope', [{**SCOPE, 'source': 'browser'}, {**SCOPE, 'device_id': OTHER},
                                 {**SCOPE, 'device_id': OTHER, 'client_id': OTHER}])
def test_brain_route_cannot_borrow_browser_or_foreign_device_scope(fixture, scope):
    with TestClient(fixture.app) as client:
        result = client.get(PATH, params=scope, headers=AUTH)
    assert result.status_code in {403, 422}
    assert fixture.service.policy(fixture.binding)['revision'] == 0


def test_direct_archive_route_requires_existing_service_auth_and_exact_query(fixture):
    with TestClient(fixture.app) as client:
        assert client.get(PATH, params=SCOPE).status_code == 401
        assert client.get(PATH, params={**SCOPE, 'owner_id': 'personal:other'}, headers=AUTH).status_code == 422
        assert client.get(PATH, params={**SCOPE, 'actor_id': '0'*64}, headers=AUTH).status_code == 422
    assert fixture.service.policy(fixture.binding)['revision'] == 0


def test_clear_keeps_family_legacy_rows_profiles_and_working_policy(fixture):
    with fixture.memory.connect() as db:
        db.execute('INSERT INTO conversations VALUES(?,?,?)', ('family-private', 'personal:other', 1))
        db.execute('INSERT INTO messages(conversation_id,role,content,provider,created) VALUES(?,?,?,?,?)',
                   ('family-private', 'user', 'HOUSEHOLD_CANARY', 'fixture', 1))
    working = fixture.root/'data/working-memory-policy.json'
    working.write_text('{"fixture":"working checkpoint retention unchanged"}')
    before = working.read_bytes()
    with sqlite3.connect(fixture.devices.db) as db:
        profiles = list(db.execute('SELECT * FROM profiles ORDER BY owner'))
    with TestClient(fixture.panel, base_url=LOCAL, client=('127.0.0.1', 50000)) as client:
        assert client.post(ADMIN, headers=ORIGIN, json=configure()).status_code == 200
        result = client.post(ADMIN, headers=ORIGIN, json=clear(1))
        assert result.status_code == 200 and result.json()['archive']['counts']['messages'] == 0
        assert_private(result.json())
    with fixture.memory.connect() as db:
        assert db.execute('SELECT content FROM messages WHERE conversation_id=?',
                          ('family-private',)).fetchone()[0] == 'HOUSEHOLD_CANARY'
    with sqlite3.connect(fixture.devices.db) as db:
        assert list(db.execute('SELECT * FROM profiles ORDER BY owner')) == profiles
    assert working.read_bytes() == before


def test_missing_or_ambiguous_enrollment_never_creates_a_profile(fixture):
    with sqlite3.connect(fixture.devices.db) as db:
        db.execute('INSERT INTO profiles VALUES(?,?)', (BOARD+'@another', fixture.profile.model_dump_json()))
    with TestClient(fixture.panel, base_url=LOCAL, client=('127.0.0.1', 50000)) as client:
        result = client.get(ADMIN)
        assert result.status_code == 503 and result.json()['detail'] == 'admin_profile_ambiguous'
        assert not fixture.calls
    with sqlite3.connect(fixture.devices.db) as db:
        db.execute('DELETE FROM profiles WHERE owner LIKE ?', (BOARD+'@%',))
    with TestClient(fixture.panel, base_url=LOCAL, client=('127.0.0.1', 50000)) as client:
        assert client.post(ADMIN, headers=ORIGIN, json=configure()).status_code == 503
    with sqlite3.connect(fixture.devices.db) as db:
        assert db.execute('SELECT count(*) FROM profiles').fetchone()[0] == 1


def test_lost_post_reply_is_resolved_by_exact_get_receipt_without_retry(fixture):
    fixture.failure['lose_reply'] = True
    body = configure()
    with TestClient(fixture.panel, base_url=LOCAL, client=('127.0.0.1', 50000)) as client:
        lost = client.post(ADMIN, headers=ORIGIN, json=body)
        assert lost.status_code == 503 and lost.json()['detail'] == 'archive_unavailable'
        result = client.get(ADMIN, params={'operation_id': body['operation_id']})
        state = result.json()['archive']
        assert state['revision'] == 1 and state['policy'] == POLICY
        assert state['operation']['id'] == body['operation_id'] and state['operation']['replayed'] is True
    assert [request.method for request in fixture.calls] == ['POST', 'GET']
    assert_private(lost.json())


class IdleFlow:
    def __init__(self):
        self.checks = 0
        self.refreshes = []
        self.busy = False
        self.session = SimpleNamespace(id='existing', closed=False,
            offer=SimpleNamespace(device_id=BOARD, client_id=BOARD),
            lock=asyncio.Lock(), activation_lock=asyncio.Lock(), memory_flow=self)

    def require_archive_idle(self):
        assert self.session.lock.locked() and self.session.activation_lock.locked()
        self.checks += 1
        if self.busy:
            raise ValueError('archive_change_requires_idle')

    async def archive_changed(self, *, clear_context=False):
        assert self.session.lock.locked() and self.session.activation_lock.locked()
        self.refreshes.append(clear_context)


def test_active_idle_change_uses_existing_locks_and_only_clears_context_when_required(fixture):
    flow = IdleFlow()
    fixture.manager.sessions[flow.session.id] = flow.session
    with TestClient(fixture.panel, base_url=LOCAL, client=('127.0.0.1', 50000)) as client:
        assert client.post(ADMIN, headers=ORIGIN, json=configure()).status_code == 200
        assert flow.refreshes == [False]
        assert flow.checks >= 3
        body = configure(1, operation='archive-disable-read-1', values={**POLICY, 'read_enabled': False})
        assert client.post(ADMIN, headers=ORIGIN, json=body).status_code == 200
        assert flow.refreshes == [False, True]
        assert client.post(ADMIN, headers=ORIGIN, json=body).status_code == 200
        assert flow.refreshes == [False, True]


def test_busy_live_turn_blocks_mutation_but_offline_metadata_stays_available(fixture):
    flow = IdleFlow()
    flow.busy = True
    fixture.manager.sessions[flow.session.id] = flow.session
    with TestClient(fixture.panel, base_url=LOCAL, client=('127.0.0.1', 50000)) as client:
        assert client.get(ADMIN).status_code == 200
        result = client.post(ADMIN, headers=ORIGIN, json=configure())
    assert result.status_code == 409 and result.json()['detail'] == 'archive_change_requires_idle'
    assert fixture.service.policy(fixture.binding)['revision'] == 0 and not flow.refreshes


def test_profile_binding_change_before_commit_rejects_without_receipt_or_policy(fixture, monkeypatch):
    original = fixture.service.configure

    def changed(*args, **kwargs):
        with sqlite3.connect(fixture.devices.db) as db:
            db.execute('UPDATE profiles SET owner=? WHERE owner=?', (BOARD+'@new-owner', BOARD+'@guest'))
        return original(*args, **kwargs)

    monkeypatch.setattr(fixture.service, 'configure', changed)
    with TestClient(fixture.panel, base_url=LOCAL, client=('127.0.0.1', 50000)) as client:
        result = client.post(ADMIN, headers=ORIGIN, json=configure())
    assert result.status_code == 409 and result.json()['detail'] == 'archive_context_changed'
    assert fixture.service.policy(fixture.binding)['revision'] == 0
    with fixture.memory.connect() as db:
        assert db.execute('SELECT count(*) FROM native_archive_operations').fetchone()[0] == 0


def test_input_start_at_commit_fence_rolls_back_policy_and_receipt(fixture, monkeypatch):
    flow = IdleFlow()
    fixture.manager.sessions[flow.session.id] = flow.session
    original = fixture.service.configure

    def changes_at_commit(*args, **kwargs):
        current = kwargs['is_current']
        calls = 0

        def checked():
            nonlocal calls
            calls += 1
            if calls == 2:
                flow.busy = True
            return current()

        return original(*args, **{**kwargs, 'is_current': checked})

    monkeypatch.setattr(fixture.service, 'configure', changes_at_commit)
    with TestClient(fixture.panel, base_url=LOCAL, client=('127.0.0.1', 50000)) as client:
        result = client.post(ADMIN, headers=ORIGIN, json=configure())
    assert result.status_code == 409 and result.json()['detail'] == 'archive_context_changed'
    assert fixture.service.policy(fixture.binding)['revision'] == 0 and not flow.refreshes
    with fixture.memory.connect() as db:
        assert db.execute('SELECT count(*) FROM native_archive_operations').fetchone()[0] == 0


def test_refresh_failure_preserves_receipt_and_reports_live_context_failure(fixture):
    flow = IdleFlow()

    async def failure(**kwargs):
        raise RuntimeError('archive_context_reset_required')

    flow.archive_changed = failure
    fixture.manager.sessions[flow.session.id] = flow.session
    with TestClient(fixture.panel, base_url=LOCAL, client=('127.0.0.1', 50000)) as client:
        result = client.post(ADMIN, headers=ORIGIN, json=configure())
        assert result.status_code == 503
        assert result.json()['detail'] == 'archive_context_reset_required'
        state = client.get(ADMIN, params={'operation_id': configure()['operation_id']}).json()['archive']
    assert state['policy'] == POLICY and state['operation']['applied_revision'] == 1


def test_unknown_backend_error_is_redacted_without_success_claim(fixture, monkeypatch):
    def failure(*args, **kwargs):
        raise RuntimeError('HOUSEHOLD_CANARY')

    monkeypatch.setattr(fixture.service, 'status', failure)
    with TestClient(fixture.panel, base_url=LOCAL, client=('127.0.0.1', 50000)) as client:
        result = client.get(ADMIN)
    assert result.status_code == 503 and result.json() == {'detail': 'archive_unavailable'}
