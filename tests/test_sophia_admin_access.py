"""Private owner access and safe status, independent of provider/model calls."""
import hashlib
import json

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from gobot.sophia_admin_access import owner_boundary, safe_runtime_status


OWNER = 'owner@example.invalid'
TAILNET = 'https://plan.tailffc57c.ts.net'
LOCAL = 'http://127.0.0.1:18811'


def setup(tmp_path, *, enabled=True):
    (tmp_path/'data').mkdir()
    (tmp_path/'data/sophia-admin-owner.json').write_text(json.dumps({
        'version': 1, 'owner_login_sha256': hashlib.sha256(OWNER.encode()).hexdigest(),
        'local_owner_enabled': enabled,
    }))
    check = owner_boundary(tmp_path)
    app = FastAPI()

    @app.api_route('/owner', methods=['GET', 'POST'])
    def owner(request: Request):
        return {'actor': check(request, write=request.method == 'POST')}

    return app


def test_local_owner_and_verified_tailnet_owner_share_actor(tmp_path):
    app = setup(tmp_path)
    with TestClient(app, base_url=LOCAL, client=('127.0.0.1', 50000)) as client:
        local = client.post('/owner', headers={'Origin': LOCAL})
        assert local.status_code == 200
    with TestClient(app, base_url=TAILNET, client=('127.0.0.1', 50000)) as client:
        remote = client.post('/owner', headers={'Origin': TAILNET, 'Tailscale-User-Login': OWNER})
        assert remote.status_code == 200
        assert local.json() == remote.json()
        assert OWNER not in remote.text


def test_missing_wrong_duplicate_guest_or_tagged_identity_cannot_admin(tmp_path):
    app = setup(tmp_path)
    with TestClient(app, base_url=TAILNET, client=('127.0.0.1', 50000)) as client:
        for headers in ({}, {'Tailscale-User-Login': 'guest@example.invalid'},
                        {'Cookie': '__Host-gobot_sophia_guest=valid-looking'},
                        [('Tailscale-User-Login', OWNER), ('Tailscale-User-Login', OWNER)]):
            assert client.get('/owner', headers=headers).status_code == 403


def test_peer_host_origin_and_forwarded_headers_do_not_grant_access(tmp_path):
    app = setup(tmp_path)
    with TestClient(app, base_url=TAILNET, client=('192.0.2.2', 50000)) as client:
        assert client.get('/owner', headers={'Tailscale-User-Login': OWNER,
                                             'X-Forwarded-For': '127.0.0.1'}).status_code == 403
    with TestClient(app, base_url=LOCAL, client=('127.0.0.1', 50000)) as client:
        assert client.post('/owner').status_code == 403
        assert client.post('/owner', headers={'Origin': TAILNET}).status_code == 403
        assert client.get('/owner', headers={'Sec-Fetch-Site': 'cross-site'}).status_code == 403
        assert client.get('/owner', headers={'Tailscale-User-Login': OWNER}).status_code == 403
        assert client.get('/owner', headers={'X-Forwarded-Host': '127.0.0.1:18811'}).status_code == 403
        assert client.get('/owner', headers={'Host': 'foreign.invalid'}).status_code == 403


def test_absent_invalid_or_disabled_owner_binding_fails_closed(tmp_path):
    app = setup(tmp_path, enabled=False)
    path = tmp_path/'data/sophia-admin-owner.json'
    with TestClient(app, base_url=LOCAL, client=('127.0.0.1', 50000)) as client:
        assert client.get('/owner').status_code == 403
        path.write_text('{}')
        assert client.get('/owner').status_code == 503
        path.unlink()
        assert client.get('/owner').status_code == 503
        assert not path.exists()


def test_runtime_status_separates_stale_gateway_and_unknown_cost(tmp_path):
    payload = {'status': 'connected', 'configured': True,
        'brain': {'status': {'budget': {'reported_response_estimate_usd': None, 'expires_at': None,
                       'api_token': 'never-export'}, 'active_inputs': 0},
                  'sessions': [{'session_id': 'private-id', 'conversation_id': 'private-dialogue',
                     'ready': True, 'lifecycle': {'home_context_status': 'pending', 'text': 'private'}}]},
        'device': {'device_protocol_confirmed': True, 'cloud_ready': True,
                   'device_resources': {'underrun_measurement': 'not_instrumented', 'raw': 'private',
                       'host_wake_mode': 3, 'wake_barge_frames': 31,
                       'aec_mic_avg_abs': 320, 'aec_clean_avg_abs': 120,
                       'pcm_samples': [100, -80], 'transcript': 'private'}}}
    safe = safe_runtime_status(payload, observed_at=100, gateway_observed_at=80)
    assert safe['status'] == 'stale' and not safe['gateway_fresh']
    assert safe['brain']['status']['budget']['reported_response_estimate_usd'] is None
    assert safe['device']['device_resources']['underrun_measurement'] == 'not_instrumented'
    assert safe['device']['device_resources']['host_wake_mode'] == 3
    assert safe['device']['device_resources']['wake_barge_frames'] == 31
    assert safe['device']['device_resources']['aec_clean_avg_abs'] == 120
    assert 'pcm_samples' not in safe['device']['device_resources']
    assert 'private' not in json.dumps(safe) and 'never-export' not in json.dumps(safe)
    assert safe_runtime_status(payload, observed_at=100, gateway_observed_at=99)['status'] == 'connected'
    assert not safe_runtime_status(payload, observed_at=100, gateway_observed_at=150)['gateway_fresh']


def test_admin_mount_precedes_legacy_asset_route_and_keeps_owner_control(tmp_path):
    from test_sophia_panel import setup_panel
    app, calls = setup_panel(tmp_path)
    (tmp_path/'data/sophia-admin-owner.json').write_text(json.dumps({
        'version': 1, 'owner_login_sha256': hashlib.sha256(OWNER.encode()).hexdigest(),
        'local_owner_enabled': True,
    }))
    assets = tmp_path/'services/phone/dist/admin'
    assets.mkdir(parents=True)
    (assets/'index.html').write_text('<title>Owner settings</title>')
    (assets/'admin.js').write_text('"use strict";')
    with TestClient(app, base_url=LOCAL, client=('127.0.0.1', 50000)) as client:
        assert client.get('/sophia/settings', follow_redirects=False).status_code == 307
        result = client.get('/sophia/settings/')
        assert result.status_code == 200 and 'Owner settings' in result.text
        assert 'no-store' in result.headers['cache-control']
        assert "script-src 'self'" in result.headers['content-security-policy']
        assert client.get('/sophia/settings/admin.js').status_code == 200
        assert client.get('/sophia/settings/keys.json').status_code == 404
        assert client.get('/api/sophia/admin/settings').status_code == 503
        assert not (tmp_path/'data/browser-devices/profiles.sqlite').exists()
    with TestClient(app, base_url=TAILNET, client=('127.0.0.1', 50000)) as client:
        assert client.get('/sophia/settings/').status_code == 403
        assert client.post('/api/sophia/admin/control', headers={'Origin': TAILNET},
                           json={'action': 'stop'}).status_code == 403
        assert not calls
        result = client.post('/api/sophia/admin/control',
            headers={'Origin': TAILNET, 'Tailscale-User-Login': OWNER},
            json={'action': 'mode', 'mode': 'expert'})
        assert result.status_code == 200
        assert json.loads(calls[-1].content) == {
            'action': 'mode', 'mode': 'expert', 'source': 'device', 'device_id': 'enrolled-column'}
