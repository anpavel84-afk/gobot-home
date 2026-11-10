import hashlib
from fastapi import FastAPI
from fastapi.testclient import TestClient
from gobot.demo2 import attach_demo2,prepare,BASELINE

def test_ab_routes_freeze_a_assets_and_select_b_without_creating_a_call(tmp_path):
    manifest=prepare(tmp_path)
    app=FastAPI();attach_demo2(app,tmp_path)
    with TestClient(app) as c:
        a=c.get('/demo2/a');b=c.get('/demo2/b')
        assert a.headers['X-GoBot-Demo-Engine']=='legacy' and BASELINE in a.headers['X-GoBot-Demo-Baseline']
        assert '/demo2/a/assets/browser.js' in a.text
        assert '/realtime.js' not in a.text
        assert 'data-conversation-engine="realtime"' in b.text
        assert '/demo2/b/device' in b.text
        js=c.get('/demo2/a/assets/browser.js')
        assert hashlib.sha256(js.content).hexdigest()==manifest['files']['browser.js']
        assert c.get('/demo2/a/assets/not-tracked.js').status_code==404
        assert 'A · Legacy' in c.get('/demo2/a/device').text

def test_modified_baseline_asset_fails_closed(tmp_path):
    prepare(tmp_path);app=FastAPI();attach_demo2(app,tmp_path)
    (tmp_path/'a/assets/browser.js').write_text('modified')
    with TestClient(app) as c:assert c.get('/demo2/a/assets/browser.js').status_code==503
