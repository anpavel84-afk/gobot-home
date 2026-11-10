"""Touches only verified GoBot processes recorded by its own launcher."""
import asyncio,json,os,sys,time,subprocess
from pathlib import Path
import httpx,psutil
ROOT=Path(__file__).resolve().parents[1];os.chdir(ROOT);keys=json.loads((ROOT/'run/keys.json').read_text());headers={'Authorization':'Bearer '+keys['api_token']};base='http://127.0.0.1:18781'
def manifest():return json.loads((ROOT/'run/processes.json').read_text())
def wait_health():
    with httpx.Client(trust_env=False,timeout=.5) as c:
        for _ in range(60):
            try:
                if c.get(base+'/healthz').status_code==200:return
            except httpx.HTTPError:pass
            time.sleep(.1)
    raise AssertionError('Health did not recover')
with httpx.Client(trust_env=False,timeout=5) as c:
    body={'text':'Контекст до перезапуска','device_id':'reliability','conversation_id':'restart-fixture','turn_id':'restart-fixture-turn','provider':'mock'}
    assert c.post(base+'/api/v1/chat',headers=headers,json=body).status_code==200
    m=manifest();worker=m['workers']['brain'];p=psutil.Process(worker['pid'])
    assert abs(p.create_time()-worker['created'])<.1 and p.cwd().lower()==str(ROOT).lower()
    # Kill only this worker's own descendants (venv redirector may be its parent on Windows).
    children=p.children(recursive=True)
    for child in reversed(children):child.terminate()
    p.terminate()
    time.sleep(1.5);wait_health()
    replay=c.post(base+'/api/v1/chat',headers=headers,json=body).json()['events']
    assert replay[0]['data']['replayed']
    turn='disconnect-'+str(int(time.time()))
    with c.stream('POST',base+'/api/v1/chat/stream',headers=headers,json={'text':'Привет','turn_id':turn,'provider':'mock'}) as response:
        for line in response.iter_lines():
            if 'text_delta' in line:break
    for _ in range(30):
        status=c.get(base+'/api/v1/turns/'+turn,headers=headers).json()['status']
        if status!='running':break
        time.sleep(.05)
    assert status=='cancelled',status
result={'host_worker_restart':'passed','sqlite_survives_process_restart':'passed','real_sse_disconnect_cleanup':'passed','docker_restart':'not tested: Docker absent','processes':manifest()}
(ROOT/'docs/reliability-results.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result,indent=2))
