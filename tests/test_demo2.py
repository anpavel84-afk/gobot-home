import hashlib,json,subprocess
from pathlib import Path
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
        assert '/demo2/a/compat.js' in a.text
        assert c.get('/demo2/a/compat.js').headers['cache-control']=='no-store'
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

def test_legacy_readiness_only_bootstraps_bound_manual_owner_grant(tmp_path,settings,monkeypatch):
    import gobot.browser as browser
    import gobot.live_agents as agents
    from gobot.device_store import DeviceStore
    monkeypatch.setattr(browser,'ROOT',tmp_path)
    monkeypatch.setattr(browser,'openai_key_present',lambda:True)
    checked=[]
    def status(consent):
        checked.append(consent)
        return {'antigravity':{'available':consent,'reason':None if consent else 'quota_consent_required'}}
    monkeypatch.setattr(agents,'agent_status',status)
    store=DeviceStore(Path(settings.db).resolve().parent/'browser-devices')
    profile=store.profile('browser-100-120-201-115@100.120.201.115')
    (tmp_path/'run').mkdir()
    grant=tmp_path/'run/legacy-owner-admission.json'
    app=browser.create_browser_app(settings)
    with TestClient(app,base_url=browser.ORIGIN,client=('100.120.201.115',1)) as c:
        denied=c.get('/api/demo2/a/readiness').json();assert not denied['manual_authorized']
        grant.write_text(json.dumps({'enabled':True,'authorization':'synthetic-owner-manual-grant','allowed_client_id':profile.client_id}))
        response=c.get('/api/demo2/a/readiness');ready=response.json()
        assert ready['manual_authorized'] and ready['cli_ready'] and not ready['automatic_calls']
        assert ready['grant_revision'] and ready['cli_provider']=='antigravity'
        assert 'synthetic-owner-manual-grant' not in response.text and profile.client_id not in response.text
        assert response.headers['cache-control']=='no-store'
    with TestClient(app,base_url=browser.ORIGIN,client=('100.90.228.125',1)) as c:
        assert not c.get('/api/demo2/a/readiness').json()['manual_authorized']
    assert checked==[False,True,False]

def test_legacy_compat_storage_and_revoked_consent():
    result=subprocess.run(['node','tests/demo2_a_compat.cjs'],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stdout+result.stderr
