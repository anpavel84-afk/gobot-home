"""Host-only additive preview flag and guarded GoBot web deployment. No model calls.

disable is the immediate rollback: it does not restore/delete any financial data.
deploy requires an idle existing Brain, B/C and hardware gateway; restarts only
the owned Brain worker and private web gateway, never the firmware or LiveKit.
"""
import argparse,hashlib,json,os,shutil,sqlite3,subprocess,sys,time
from datetime import datetime,timezone
from pathlib import Path
import httpx,psutil
ROOT=Path(__file__).resolve().parents[1]
os.chdir(ROOT);sys.path.insert(0,str(ROOT/'services/brain'))
POLICY=ROOT/'run/night-train/preview-policy.json'

def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(value,indent=2),encoding='utf8');temp.replace(path)

def request(path,optional=False):
    token=json.loads((ROOT/'run/keys.json').read_text())['api_token']
    with httpx.Client(trust_env=False,timeout=15) as client:
        r=client.get('http://127.0.0.1:18781'+path,headers={'Authorization':'Bearer '+token})
        if optional and r.status_code==404:return {'active_sessions':0}
        r.raise_for_status();return r.json()

def idle():
    main=request('/api/v1/status');b=request('/api/v1/realtime/status');c=request('/api/v1/live/status')
    board=request('/api/v1/voice-ab/b/status',optional=True)
    gateway=json.loads((ROOT/'data/hardware/gobot-v1/gateway-status.json').read_text())
    if main['active_turns'] or main['active_voice_streams'] or b['active_sessions'] or board['active_sessions'] or c['active_sessions'] or gateway['active']:
        raise RuntimeError('active_conversation_deployment_deferred')
    return main

def flag(enabled):
    if not enabled:write(POLICY,{'enabled':False});return
    from gobot.config import load
    from gobot.device_store import DeviceStore
    owner=json.loads((ROOT/'run/owner-testing/policy.json').read_text())['allowed_client_id']
    devices=DeviceStore(Path(load().db).resolve().parent/'browser-devices')
    desktop=devices.profile('browser-100-90-228-125@100.90.228.125').client_id
    write(POLICY,{'enabled':True,'owner_clients':[owner,desktop],'fixture_mode':False,
        'note':'Owner private preview; additional desktop binding grants NO paid admission'})

def backup():
    from gobot.config import load
    dest=ROOT/'run/night-train/backups'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ');dest.mkdir(parents=True)
    sources=[Path(load().db).resolve(),*[ROOT/f'run/{kind}/usage.sqlite' for kind in ('live','realtime','owner-testing')]]
    for n,path in enumerate(sources):
        if path.exists():
            with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as src,sqlite3.connect(dest/f'db-{n}.sqlite') as dst:src.backup(dst)
    for name in ('run/live/policy.json','run/realtime/policy.json','run/owner-testing/policy.json','run/night-train/preview-policy.json','run/processes.json','run/browser.json'):
        p=ROOT/name
        if p.exists():q=dest/name;q.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,q)
    shutil.copytree(ROOT/'services/phone/dist',dest/'web-dist')
    old=request('/api/v1/status')['runtime_code_commit']
    subprocess.run(['git','archive','--format=zip','--output='+str(dest/'runtime-source.zip'),old],check=True)
    write(dest/'deployment.json',{'previous_runtime':old,'candidate':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()})
    return dest

def deploy():
    import msvcrt
    lock=(ROOT/'run/night-train/deploy.lock').open('a+b');lock.seek(0);lock.write(b'1');lock.flush();lock.seek(0)
    msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
    try:
        before=idle();dest=backup();idle()
        manifest=json.loads((ROOT/'run/processes.json').read_text());entry=manifest['workers']['brain']
        p=psutil.Process(entry['pid'])
        if abs(p.create_time()-entry['created'])>.1 or Path(p.cwd()).resolve()!=ROOT or p.cmdline()[-2:]!=['worker','brain']:
            raise RuntimeError('brain_process_identity_mismatch')
        processes=p.children(recursive=True)+[p]
        for process in reversed(processes):
            if process.pid!=p.pid:process.terminate()
        p.terminate();psutil.wait_procs(processes,timeout=8)
        # Existing GoBot supervisor owns the single replacement worker.
        for _ in range(60):
            try:
                current=request('/api/v1/status')
                if current['runtime_code_commit']!=before['runtime_code_commit']:break
            except (httpx.HTTPError,OSError):pass
            time.sleep(.5)
        else:raise RuntimeError('brain_restart_not_confirmed')
        flag(True)
        subprocess.run([sys.executable,'scripts/web.py','stop'],check=True)
        time.sleep(1)
        subprocess.run([sys.executable,'scripts/web.py','start'],check=True)
        write(ROOT/'run/night-train/deployment.json',{'backup':str(dest.relative_to(ROOT)),
            'previous_runtime':before['runtime_code_commit'],'runtime':current['runtime_code_commit'],
            'url':'https://plan.tailffc57c.ts.net:18786/device-next','firmware_changed':False})
        print(json.dumps({'deployed':True,'runtime_sha':current['runtime_code_commit'],'backup':str(dest.relative_to(ROOT))}))
    finally:lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1);lock.close()

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=['status','enable','disable','deploy']);args=parser.parse_args()
    if args.command=='deploy':deploy()
    elif args.command=='status':
        result=idle();print(json.dumps({'idle':True,'runtime':result['runtime_code_commit'],'preview_enabled':json.loads(POLICY.read_text()).get('enabled') if POLICY.exists() else False}))
    else:flag(args.command=='enable');print('Preview '+args.command+'d; financial policies and history unchanged')
