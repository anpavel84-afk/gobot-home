import asyncio,json,subprocess,shutil
from pathlib import Path
import httpx
from fastapi.testclient import TestClient

ROOT=Path(__file__).resolve().parents[1]

def test_microphone_click_independent_of_playback_and_pointer_capture():
    result=subprocess.run([shutil.which('node'),'tests/browser_microphone.cjs'],cwd=ROOT,capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stderr

def test_login_status_survives_gateway_restart(tmp_path,monkeypatch):
    import gobot.antigravity_login as login
    monkeypatch.setattr(login,'ROOT',tmp_path)
    (tmp_path/'run').mkdir();(tmp_path/'run/antigravity-audit.json').write_text(json.dumps({'oauth_authenticated':True}))
    status=login.AntigravityLogin().status()
    assert status['state']=='authenticated' and status['oauth_cached'] is True and status['authorization_url'] is None

def test_uncertain_voice_revokes_personal_context(settings,monkeypatch):
    import gobot.browser as browser
    real_client=httpx.AsyncClient;forwarded=[]
    profile='11111111-1111-1111-1111-111111111111'
    async def backend(request):
        path=request.url.path
        if path.endswith('/family/login'):return httpx.Response(200,json={'id':profile,'epoch':'fixture','name':'Тест'})
        if path.endswith('/family/session'):return httpx.Response(200,json={'valid':True})
        if '/speaker/' in path:return httpx.Response(200,json={'state':'unknown','reason':'identity_pending'})
        if path.endswith('/chat/voice/stream'):
            body=json.loads(request.content);forwarded.append(body)
            return httpx.Response(200,content='event: final\ndata: {"type":"final","data":{"text":"fixture","mock":true}}\n\n')
        return httpx.Response(404)
    monkeypatch.setattr(browser.httpx,'AsyncClient',lambda **kwargs:real_client(transport=httpx.MockTransport(backend),**kwargs))
    with TestClient(browser.create_browser_app(settings),base_url=browser.ORIGIN,client=('100.120.201.115',1234)) as client:
        headers={'Origin':browser.ORIGIN}
        assert client.post('/api/family/login',headers=headers,json={'profile_id':profile,'pin':'fixture-pin'}).status_code==200
        response=client.post('/api/chat/stream',headers=headers,json={'text':'Что я спрашивал?','mode':'mock','speaker_job_id':'22222222-2222-2222-2222-222222222222','conversation_id':'previous-private'})
        assert response.status_code==200 and 'guest_context' in response.text
        assert forwarded[0]['device_id']=='browser-100-120-201-115'
        assert forwarded[0]['conversation_id']!='previous-private'
        assert 'gobot_profile' not in client.cookies

def test_metrics_have_counts_and_no_fabricated_physical_playback(settings):
    from gobot.memory import Memory
    memory=Memory(settings.db)
    memory.record_metrics('fixture','fixture',{'llm_first_token':10,'stt_final':20,'first_physical_audio':0,'invalid':1})
    summary=memory.metric_summary()
    assert summary['fixture:llm_first_token']['p50']==10
    assert len(summary)==2 and all('physical' not in key for key in summary)
