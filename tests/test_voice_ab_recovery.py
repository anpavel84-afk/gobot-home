"""Administrative resource probes use loopback mocks, never provider endpoints."""
import asyncio,importlib.util,json
from pathlib import Path
import httpx,pytest

spec=importlib.util.spec_from_file_location('voice_ab_recovery',Path(__file__).resolve().parents[1]/'scripts/voice_ab_recovery.py')
admin=importlib.util.module_from_spec(spec);spec.loader.exec_module(admin)

def files(tmp_path):
    private=tmp_path/'data/hardware/gobot-v1';(private/'livekit').mkdir(parents=True)
    (private/'gateway.json').write_text(json.dumps({'brain_url':'http://127.0.0.1:18781','bind':'192.168.1.9','port':18789}))
    (private/'livekit/private.json').write_text(json.dumps({'url':'ws://127.0.0.1:17880','key':'fixture','secret':'fixture-secret-long-enough-for-hmac-256'}))
    (tmp_path/'run').mkdir();(tmp_path/'run/keys.json').write_text('{"api_token":"fixture"}')

@pytest.mark.parametrize('close',[False,True])
def test_exact_old_room_only_and_never_provider_calls(tmp_path,close):
    files(tmp_path);requests=[];present=[True]
    def handler(request):
        requests.append(request)
        assert request.url.host=='127.0.0.1'
        if request.method=='GET':return httpx.Response(200,json={'active_sessions':0})
        if request.url.path.endswith('/DeleteRoom'):
            assert close and json.loads(request.content)=={'room':'gobot-old'}
            present[0]=False;return httpx.Response(200,json={})
        assert json.loads(request.content)=={'names':['gobot-old']}
        return httpx.Response(200,json={'rooms':[{'name':'gobot-old'}] if present[0] else []})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            if close:assert all((await admin.verify_local(tmp_path,'old',client=client,listener=lambda:False,close_old_room=True)).values())
            else:
                with pytest.raises(ValueError,match='old_relay_still_present'):await admin.verify_local(tmp_path,'old',client=client,listener=lambda:False)
    asyncio.run(run())
    assert sum(r.url.path.endswith('/DeleteRoom') for r in requests)==int(close)

@pytest.mark.parametrize('case',['gateway_active','brain_active','503','other_room','gateway_restarted'])
def test_unsafe_or_unverifiable_resources_fail_closed(tmp_path,case):
    files(tmp_path);listeners=iter([False,True] if case=='gateway_restarted' else [case=='gateway_active',False])
    def handler(request):
        assert not request.url.path.endswith('/DeleteRoom')
        if request.method=='GET':return httpx.Response(200,json={'active_sessions':int(case=='brain_active')})
        if case=='503':return httpx.Response(503)
        return httpx.Response(200,json={'rooms':[{'name':'another-session'}]} if case=='other_room' else {})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises((ValueError,httpx.HTTPStatusError)):
                await admin.verify_local(tmp_path,'old',client=client,listener=lambda:next(listeners))
    asyncio.run(run())

def test_backup_includes_wal(tmp_path):
    import sqlite3
    source=tmp_path/'source.sqlite';target=tmp_path/'backup.sqlite'
    with sqlite3.connect(source) as db:
        db.execute('PRAGMA journal_mode=WAL');db.execute('CREATE TABLE evidence(value)')
        db.execute('INSERT INTO evidence VALUES(17)');db.commit()
        admin.backup_sqlite(source,target)
    with sqlite3.connect(target) as db:assert db.execute('SELECT value FROM evidence').fetchone()==(17,)
