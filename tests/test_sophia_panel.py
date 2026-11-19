import json
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gobot.sophia_panel import attach_sophia_panel


def setup_panel(tmp_path):
    (tmp_path/'run').mkdir()
    (tmp_path/'run/keys.json').write_text(json.dumps({'api_token': 'test-key-never-sent-to-browser'}))
    private=tmp_path/'data/hardware/gobot-v1'
    private.mkdir(parents=True)
    (private/'gateway.json').write_text(json.dumps({'device_id':'enrolled-column','unified_voice':{'enabled':True}}))
    (private/'gateway-status.json').write_text(json.dumps({'unified':{
        'device_protocol_confirmed':True,'cloud_ready':False,'last_error':'board_budget_inactive',
        'private_field':'must-not-leave-server'}}))
    calls=[]
    def backend(request):
        calls.append(request)
        if request.url.path.endswith('/status'):
            return httpx.Response(200,json={'status':{'enabled':False},'sessions':[]})
        return httpx.Response(200,json={'accepted':True})
    app=FastAPI()
    attach_sophia_panel(app,tmp_path,client_factory=lambda **kw:httpx.AsyncClient(
        transport=httpx.MockTransport(backend),**kw))
    return app,calls


def test_panel_keeps_credentials_and_identity_on_server(tmp_path):
    app,calls=setup_panel(tmp_path)
    with TestClient(app,base_url='http://127.0.0.1:18811',client=('127.0.0.1',50000)) as client:
        response=client.get('/api/sophia/status')
        assert response.status_code==200
        assert response.json()['device']['cloud_ready'] is False
        assert 'must-not-leave-server' not in response.text
        assert 'test-key-never-sent-to-browser' not in response.text
        response=client.post('/api/sophia/control',headers={'Origin':'http://127.0.0.1:18811'},
                             json={'action':'mode','mode':'expert'})
        assert response.status_code==200
        sent=json.loads(calls[-1].content)
        assert sent=={'action':'mode','mode':'expert','source':'device','device_id':'enrolled-column'}
        assert calls[-1].headers['authorization']=='Bearer test-key-never-sent-to-browser'


def test_cross_site_and_remote_control_cannot_reuse_loopback_authority(tmp_path):
    app,calls=setup_panel(tmp_path)
    with TestClient(app,base_url='http://127.0.0.1:18811',client=('127.0.0.1',50000)) as client:
        response=client.post('/api/sophia/control',headers={'Origin':'https://foreign.invalid'},json={'action':'stop'})
        assert response.status_code==403
        response=client.post('/api/sophia/control',headers={'Origin':'http://127.0.0.1:18811'},
                             json={'action':'stop','device_id':'phone-owner'})
        assert response.status_code==422
    with TestClient(app,base_url='https://plan.tailffc57c.ts.net',client=('192.0.2.10',50000)) as client:
        assert client.get('/api/sophia/status').status_code==403
    assert not calls
