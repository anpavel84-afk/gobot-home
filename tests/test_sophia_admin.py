"""Owner weather settings: existing scope, provider proof and transaction fences."""
import asyncio
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from gobot.device_contract import DeviceProfile, WeatherPreferences
from gobot.device_store import DeviceStore
from gobot.sophia_admin import SophiaAdmin, attach_sophia_admin
from gobot.weather import WeatherError


BOARD = 'spotpear-001122aabbcc'
OTHER_BOARD = 'spotpear-112233bbccdd'
ACTOR = 'test-owner'


class Source:
    def __init__(self, clock):
        self.clock = clock
        self.error = None
        self.calls = []
        self.after_read = None

    async def locations(self, query):
        self.calls.append(('locations', query))
        if self.error:
            raise WeatherError(self.error)
        return [
            {'location_name': 'Test City, Region, Country', 'latitude': 10.123, 'longitude': 20.456},
            {'location_name': 'Other Test City, Country', 'latitude': 11.234, 'longitude': 21.567},
        ]

    async def current(self, place):
        self.calls.append(('current', place.location_name))
        if self.error:
            raise WeatherError(self.error)
        if self.after_read:
            self.after_read()
        return {'observed_at': self.clock()-42, 'fetched_at': self.clock(), 'temperature': 23,
                'apparent': 24, 'wind_kmh': 11, 'weather_code': 0, 'timezone': 'Etc/UTC'}


@pytest.fixture
def setup(tmp_path):
    now = [1795200000.0]
    clock = lambda: now[0]
    config = tmp_path/'data/hardware/gobot-v1'
    config.mkdir(parents=True)
    (config/'gateway.json').write_text(json.dumps({'device_id': BOARD, 'secret': 'must-not-leave'}))
    store = DeviceStore(tmp_path/'data/browser-devices')
    base = DeviceProfile(client_id=BOARD, client_kind='spotpear', weather=WeatherPreferences(
        enabled=True, location_name='Existing Home, Region', latitude=30.123, longitude=40.456))
    base.voice.voice = 'marin'
    base.voice.realtime_consent = True
    base.screen.generation_allowed = False
    phone = DeviceProfile()
    other = DeviceProfile(client_id=OTHER_BOARD, client_kind='spotpear')
    with sqlite3.connect(store.db) as db:
        db.executemany('INSERT INTO profiles VALUES(?,?)', [
            (BOARD+'@guest', base.model_dump_json()),
            ('phone-owner@personal', phone.model_dump_json()),
            (OTHER_BOARD+'@guest', other.model_dump_json()),
        ])
    source = Source(clock)
    service = SophiaAdmin(tmp_path, weather_client=source, clock=clock)
    return {'root': tmp_path, 'store': store, 'source': source, 'service': service, 'now': now,
            'base': base, 'phone': phone, 'other': other}


def _body(service, weather, operation='operation-1234567890'):
    return {'expected_revision': service.settings()['revision'], 'operation_id': operation,
            'patch': {'weather': weather}}


def _selected(service, *, actor=ACTOR, index=0):
    places = asyncio.run(service.locations(actor, {'query': 'Test City'}))
    candidate_id = places['candidates'][index]['id']
    proof = asyncio.run(service.verify(actor, {'candidate_id': candidate_id}))
    return {'enabled': True, 'candidate_id': candidate_id, 'verification_id': proof['verification_id']}


def _rows(store):
    with sqlite3.connect(store.db) as db:
        return dict(db.execute('SELECT owner,profile FROM profiles'))


def test_get_is_existing_read_only_scope_and_redacts_coordinates(setup):
    service, store, source = setup['service'], setup['store'], setup['source']
    before = store.db.read_bytes()
    result = service.settings()
    assert result['target']['id'] == BOARD
    assert result['settings']['weather'] == {'enabled': True, 'provider': 'open_meteo',
                                             'location_name': 'Existing Home, Region'}
    assert result['application']['device_acknowledged'] is False
    serialized = json.dumps(result)
    assert all(value not in serialized for value in ('latitude', 'longitude', 'must-not-leave', '30.123', 'phone-owner'))
    assert service.changes(ACTOR) == []
    assert source.calls == []
    assert before == store.db.read_bytes()


def test_missing_profile_storage_is_not_created(tmp_path):
    service = SophiaAdmin(tmp_path)
    with pytest.raises(HTTPException) as error:
        service.settings()
    assert error.value.status_code == 503
    assert not (tmp_path/'data').exists()


@pytest.mark.parametrize('change', ['duplicate', 'wrong_kind', 'missing', 'wrong_target'])
def test_column_scope_never_falls_back_to_browser_or_other_column(setup, change):
    store, service = setup['store'], setup['service']
    with sqlite3.connect(store.db) as db:
        if change == 'duplicate':
            db.execute('INSERT INTO profiles VALUES(?,?)', (BOARD+'@second', setup['base'].model_dump_json()))
        elif change == 'wrong_kind':
            db.execute('UPDATE profiles SET profile=? WHERE owner=?', (setup['phone'].model_dump_json(), BOARD+'@guest'))
        elif change == 'missing':
            db.execute('DELETE FROM profiles WHERE owner=?', (BOARD+'@guest',))
        else:
            service.config.write_text(json.dumps({'device_id': 'spotpear-ffffffffffff'}))
    before = store.db.read_bytes()
    with pytest.raises(HTTPException) as error:
        service.settings()
    assert error.value.status_code == 503
    assert before == store.db.read_bytes()


def test_verified_save_only_changes_target_weather_and_is_idempotent_after_restart(setup):
    service, store, source = setup['service'], setup['store'], setup['source']
    before = _rows(store)
    weather = _selected(service)
    body = _body(service, weather)
    preview_body = {key: value for key, value in body.items() if key != 'operation_id'}
    preview = service.validate(ACTOR, preview_body)
    assert preview['changes'] == [{'field': 'weather.location_name', 'before': 'Existing Home, Region',
                                    'after': 'Test City, Region, Country'}]
    assert _rows(store) == before
    result = service.apply(ACTOR, body)
    assert result['ok'] and not result['idempotent'] and not result['unchanged']
    assert result['settings']['weather_check']['verified'] is True
    after = _rows(store)
    assert after['phone-owner@personal'] == before['phone-owner@personal']
    assert after[OTHER_BOARD+'@guest'] == before[OTHER_BOARD+'@guest']
    old, new = json.loads(before[BOARD+'@guest']), json.loads(after[BOARD+'@guest'])
    assert new['weather']['latitude'] == 10.123
    assert {k: v for k, v in old.items() if k != 'weather'} == {k: v for k, v in new.items() if k != 'weather'}
    restarted = SophiaAdmin(setup['root'], weather_client=source, clock=lambda: setup['now'][0])
    repeated = restarted.apply(ACTOR, body)
    assert repeated['idempotent'] is True
    assert repeated['change'] == result['change']
    assert _rows(store) == after
    assert len(restarted.changes(ACTOR)) == 1
    assert restarted.changes('another-owner') == []
    assert len(source.calls) == 2
    assert 'latitude' not in json.dumps(repeated)


def test_failed_source_never_changes_profile_or_accepts_city_selection(setup):
    service, source, store = setup['service'], setup['source'], setup['store']
    candidate = asyncio.run(service.locations(ACTOR, {'query': 'Test City'}))['candidates'][0]['id']
    before = store.db.read_bytes()
    source.error = 'weather_source_timeout'
    with pytest.raises(HTTPException) as error:
        asyncio.run(service.verify(ACTOR, {'candidate_id': candidate}))
    assert error.value.detail == 'weather_source_timeout'
    with pytest.raises(HTTPException) as error:
        service.apply(ACTOR, _body(service, {'enabled': True, 'candidate_id': candidate}))
    assert error.value.detail == 'verification_expired'
    assert store.db.read_bytes() == before
    assert service.changes(ACTOR) == []


@pytest.mark.parametrize('field,value', [
    ('latitude', 10), ('longitude', 20), ('location_name', 'Forged City'),
    ('provider', 'other'), ('enabled', 'true'), ('enabled', 1), ('candidate_id', '../../secret'),
])
def test_browser_cannot_inject_raw_location_or_settings(setup, field, value):
    service, store = setup['service'], setup['store']
    before = store.db.read_bytes()
    with pytest.raises(HTTPException) as error:
        service.apply(ACTOR, _body(service, {field: value}))
    assert error.value.status_code == 422
    assert store.db.read_bytes() == before


def test_browser_cannot_choose_profile_or_add_voice_permissions(setup):
    service, store = setup['service'], setup['store']
    before = store.db.read_bytes()
    for body in [
        {**_body(service, {'enabled': False}), 'device_id': OTHER_BOARD},
        {**_body(service, {'enabled': False}), 'patch': {'voice': {'realtime_consent': True}}},
    ]:
        with pytest.raises(HTTPException) as error:
            service.apply(ACTOR, body)
        assert error.value.status_code == 422
    assert store.db.read_bytes() == before


def test_candidate_and_verification_are_actor_bound(setup):
    service, store = setup['service'], setup['store']
    patch = _selected(service)
    before = store.db.read_bytes()
    with pytest.raises(HTTPException) as error:
        asyncio.run(service.verify('other-owner', {'candidate_id': patch['candidate_id']}))
    assert error.value.detail == 'weather_candidate_expired'
    with pytest.raises(HTTPException) as error:
        service.apply('other-owner', _body(service, patch))
    assert error.value.status_code == 410
    assert store.db.read_bytes() == before


def test_proof_must_match_selected_candidate(setup):
    service = setup['service']
    first, second = _selected(service), _selected(service, index=1)
    patch = {**second, 'verification_id': first['verification_id']}
    with pytest.raises(HTTPException) as error:
        service.apply(ACTOR, _body(service, patch))
    assert error.value.detail == 'weather_verification_mismatch'


def test_expiry_and_failed_check_replace_success_status(setup):
    service, source = setup['service'], setup['source']
    asyncio.run(service.verify(ACTOR, {}))
    assert service.settings()['weather_check']['verified'] is True
    source.error = 'weather_source_timeout'
    with pytest.raises(HTTPException):
        asyncio.run(service.verify(ACTOR, {}))
    assert service.settings()['weather_check']['verified'] is False
    assert service.settings()['weather_check']['reason_code'] == 'weather_source_timeout'
    setup['now'][0] += 301
    assert service.settings()['weather_check'] is None


def test_expired_verification_cannot_write(setup):
    service, store = setup['service'], setup['store']
    patch = _selected(service)
    body = _body(service, patch)
    before = store.db.read_bytes()
    setup['now'][0] += 301
    with pytest.raises(HTTPException) as error:
        service.apply(ACTOR, body)
    assert error.value.detail == 'verification_expired'
    assert store.db.read_bytes() == before


def test_later_failed_verification_revokes_earlier_candidate_proof(setup):
    service, source, store = setup['service'], setup['source'], setup['store']
    patch = _selected(service)
    source.error = 'weather_source_timeout'
    with pytest.raises(HTTPException):
        asyncio.run(service.verify(ACTOR, {'candidate_id': patch['candidate_id']}))
    before = store.db.read_bytes()
    with pytest.raises(HTTPException) as error:
        service.apply(ACTOR, _body(service, patch))
    assert error.value.detail == 'verification_expired'
    assert store.db.read_bytes() == before


def test_verification_expiry_never_outlives_selected_candidate(setup):
    service = setup['service']
    result = asyncio.run(service.locations(ACTOR, {'query': 'Test City'}))
    setup['now'][0] += 590
    proof = asyncio.run(service.verify(ACTOR, {'candidate_id': result['candidates'][0]['id']}))
    assert proof['expires_at'] == result['expires_at']


def test_existing_device_store_change_invalidates_revision_and_old_proof(setup):
    service, store = setup['service'], setup['store']
    patch = _selected(service)
    body = _body(service, patch)
    store.update(BOARD+'@guest', {'voice': {'volume': 0.6}})
    before = store.db.read_bytes()
    with pytest.raises(HTTPException) as error:
        service.apply(ACTOR, body)
    assert error.value.detail == 'revision_conflict'
    body['expected_revision'] = service.settings()['revision']
    with pytest.raises(HTTPException) as error:
        service.apply(ACTOR, body)
    assert error.value.detail == 'revision_conflict'
    assert store.db.read_bytes() == before


def test_revision_change_during_provider_check_invalidates_confirmation(setup):
    service, source, store = setup['service'], setup['source'], setup['store']
    source.after_read = lambda: store.update(BOARD+'@guest', {'voice': {'volume': 0.7}})
    with pytest.raises(HTTPException) as error:
        asyncio.run(service.verify(ACTOR, {}))
    assert error.value.detail == 'revision_conflict'
    assert service.settings()['weather_check'] is None


def test_disabled_location_is_preserved_and_reenable_requires_source_proof(setup):
    service, store = setup['service'], setup['store']
    disabled = service.apply(ACTOR, _body(service, {'enabled': False}))
    assert disabled['settings']['settings']['weather']['enabled'] is False
    profile = store.profile(BOARD+'@guest')
    assert profile.weather.latitude == setup['base'].weather.latitude
    assert profile.weather.location_name == setup['base'].weather.location_name
    with pytest.raises(HTTPException) as error:
        service.apply(ACTOR, _body(service, {'enabled': True}, 'operation-enable-123456'))
    assert error.value.detail == 'verification_expired'
    proof = asyncio.run(service.verify(ACTOR, {}))
    assert proof['candidate_id'] is None
    enabled = service.apply(ACTOR, _body(service, {'enabled': True,
                           'verification_id': proof['verification_id']}, 'operation-enable-123456'))
    assert enabled['settings']['settings']['weather']['enabled'] is True
    assert len(service.changes(ACTOR)) == 2


def test_unchanged_apply_does_not_create_history_or_mutate_db(setup):
    service, store = setup['service'], setup['store']
    before = store.db.read_bytes()
    result = service.apply(ACTOR, _body(service, {'enabled': True}))
    assert result['unchanged'] and result['change'] is None
    assert service.changes(ACTOR) == []
    assert before == store.db.read_bytes()


def test_operation_id_cannot_be_reused_with_different_payload_or_actor(setup):
    service = setup['service']
    body = _body(service, {'enabled': False})
    service.apply(ACTOR, body)
    with pytest.raises(HTTPException) as error:
        service.apply('other-owner', body)
    assert error.value.detail == 'operation_conflict'
    with pytest.raises(HTTPException) as error:
        service.apply(ACTOR, _body(service, {'enabled': True}))
    assert error.value.detail == 'operation_conflict'


def test_two_parallel_editors_cannot_overwrite_each_other(setup):
    service = setup['service']
    body = _body(service, {'enabled': False})
    second = {**body, 'operation_id': 'operation-another-123456'}
    other = SophiaAdmin(setup['root'], weather_client=setup['source'], clock=lambda: setup['now'][0])
    def apply(target, data):
        try:
            return target.apply(ACTOR, data)
        except HTTPException as error:
            return {'error': error.detail}
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(apply, service, body), executor.submit(apply, other, second)]
        results = [future.result() for future in futures]
    assert sum(result.get('ok') is True for result in results) == 1
    assert sum(result.get('error') == 'revision_conflict' for result in results) == 1
    assert len(service.changes(ACTOR)) == 1


def test_transaction_failure_rolls_back_profile_and_receipt(setup):
    service, store = setup['service'], setup['store']
    before = _rows(store)
    with sqlite3.connect(store.db) as db:
        service._operation_table(db)
        db.execute("CREATE TRIGGER fail_admin_audit BEFORE INSERT ON sophia_admin_operations "
                   "BEGIN SELECT RAISE(ABORT, 'audit_failed'); END")
    with pytest.raises(HTTPException) as error:
        service.apply(ACTOR, _body(service, {'enabled': False}))
    assert error.value.detail == 'admin_settings_unavailable'
    assert _rows(store) == before
    assert service.changes(ACTOR) == []


def test_http_routes_call_owner_boundary_for_reads_and_source_operations(setup):
    calls = []
    def authenticate(request, write=False):
        calls.append((request.url.path, write))
        if request.headers.get('x-test-owner') != 'yes':
            raise HTTPException(403, 'admin_owner_required')
        return ACTOR
    app = FastAPI()
    attach_sophia_admin(app, setup['root'], authenticate=authenticate,
                        runtime_status=lambda: {'status': 'connected', 'brain': {'sessions': []}},
                        weather_client=setup['source'], clock=lambda: setup['now'][0])
    with TestClient(app) as client:
        assert client.get('/api/sophia/admin/snapshot').status_code == 403
        response = client.get('/api/sophia/admin/snapshot', headers={'x-test-owner': 'yes'})
        assert response.status_code == 200
        assert response.headers['cache-control'] == 'no-store'
        assert response.json()['runtime']['status'] == 'connected'
        assert response.json()['changes'] == []
        assert setup['source'].calls == []
        verify = client.post('/api/sophia/admin/weather/verify', json={}, headers={'x-test-owner': 'yes'})
        assert verify.status_code == 200
        assert verify.json()['verified'] is True
        assert 'latitude' not in verify.text
        assert calls[-1][1] is True
        denied = client.post('/api/sophia/admin/settings/apply', json=_body(setup['service'], {'enabled': False}))
        assert denied.status_code == 403
    assert setup['store'].profile(BOARD+'@guest').weather.enabled is True
