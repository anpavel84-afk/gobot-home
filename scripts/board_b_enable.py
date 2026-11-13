"""Explicit local Owner operation: prepare/mount, activate, status, rollback.

Never creates provider sessions, changes allowance caps, flashes firmware or
restores financial databases. Only the existing enrolled gateway may be recycled.
"""
import argparse,json,os,shutil,socket,sqlite3,subprocess,sys,time
from datetime import datetime,timezone
from pathlib import Path
import psutil
from night_preview import ROOT,idle,write,request
sys.path.insert(0,str(ROOT/'services/brain'))
from gobot.board_realtime import BoardBudget

PRIVATE=ROOT/'data/hardware/gobot-v1';BROOT=ROOT/'run/voice-ab-b'
CONFIG=PRIVATE/'gateway.json';STATE=BROOT/'deployment.json'

def policy():
    b=BoardBudget(BROOT);p=b.policy();g=json.loads(CONFIG.read_text(encoding='utf8'))
    assert p.allowed_client_id==g['device_id'] and p.authorization
    assert (p.max_sessions,p.max_session_seconds,p.max_responses_per_session,p.max_output_tokens)==(8,60,8,512)
    assert p.model=='gpt-realtime-2.1-mini' and p.allowed_models==[p.model] and p.voice=='marin' and p.input_transcription
    assert not any((p.owner_full_test,p.expert_jobs_allowed,p.image_generation_allowed,p.device_settings_allowed))
    return b,p,g

def prepare():
    idle();b,p,g=policy();assert g['mode']=='live_c' and not p.enabled
    assert not b.pending_calls()
    folder=BROOT/'backups'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ');folder.mkdir(parents=True)
    shutil.copy2(CONFIG,folder/'gateway.json');shutil.copy2(b.policy_path,folder/'policy.json')
    for kind in ('live','realtime','owner-testing','voice-ab-b'):
        source=ROOT/f'run/{kind}/usage.sqlite'
        if source.exists():
            with sqlite3.connect(source.as_uri()+'?mode=ro',uri=True) as src,sqlite3.connect(folder/(kind+'.sqlite')) as dst:src.backup(dst)
    write(STATE,{'backup':str(folder.relative_to(ROOT)),'phase':'prepared','automatic_paid_calls':0})
    write(BROOT/'mount.json',{'enabled':True});write(b.policy_path,{**p.model_dump(),'enabled':True})
    print(json.dumps({'prepared':True,'caps_changed':False,'backup':str(folder.relative_to(ROOT)),'next':'guarded idle Brain deployment, then activate'}))

def gateway_restart():
    script=(ROOT/'services/voice/gobot_device_gateway.py').resolve();g=json.loads(CONFIG.read_text())
    candidates={}
    for p in psutil.process_iter(['pid','cmdline']):
        args=p.info['cmdline'] or []
        if any(a.endswith('gobot_device_gateway.py') and Path(a).resolve()==script for a in args):
            if Path(p.cwd()).resolve()==ROOT:candidates[p.pid]=p
    listeners={c.pid for c in psutil.net_connections(kind='tcp') if c.laddr and c.laddr.port==g['port'] and not c.raddr}
    owned=[p for pid,p in candidates.items() if pid in listeners]
    if len(owned)!=1:raise RuntimeError('exact_gateway_listener_not_verified')
    p=owned[0];parent=p.parent();processes=[p]+([parent] if parent and parent.pid in candidates else [])
    for process in processes:process.terminate()
    _,alive=psutil.wait_procs(processes,timeout=5)
    if alive:raise RuntimeError('gateway_stop_not_confirmed')
    env=os.environ.copy();env['PYTHONUTF8']='1'
    with (PRIVATE/'realtime-b-runtime.log').open('ab') as log:
        child=subprocess.Popen([str(ROOT/'.venv/Scripts/python.exe'),str(script),'--config',str(CONFIG)],cwd=ROOT,env=env,
            stdin=subprocess.DEVNULL,stdout=log,stderr=log,creationflags=0x08000000)
    for _ in range(80):
        if child.poll() is not None:raise RuntimeError('gateway_start_failed')
        state=json.loads((PRIVATE/'gateway-status.json').read_text())
        with socket.socket() as s:
            s.settimeout(.2);listening=s.connect_ex((g['bind'],g['port']))==0
        if state['mode']==g['mode'] and listening:return
        time.sleep(.1)
    raise RuntimeError('gateway_readiness_not_confirmed')

def activate():
    idle();b,p,g=policy();status=request('/api/v1/voice-ab/b/status')
    assert status['enabled'] and not status['active_sessions'] and not status['pending_hangups'] and g['mode']=='live_c'
    write(CONFIG,{**g,'mode':'realtime_b','hardware_realtime_consent':True})
    gateway_restart();state=json.loads(STATE.read_text());state.update(phase='active_manual_only',runtime=request('/api/v1/status')['runtime_code_commit']);write(STATE,state)
    print(json.dumps({'gateway':'realtime_b','sessions_remaining':b.board_status()['sessions_remaining'],'firmware_changed':False,'automatic_paid_calls':0}))

def rollback():
    idle();b,p,g=policy();state=json.loads(STATE.read_text());folder=(ROOT/state['backup']).resolve()
    assert folder.is_relative_to(BROOT/'backups')
    saved=json.loads((folder/'gateway.json').read_text());assert saved['device_id']==g['device_id'] and saved['mode']=='live_c'
    write(CONFIG,saved);write(b.policy_path,{**p.model_dump(),'enabled':False});write(BROOT/'mount.json',{'enabled':False})
    gateway_restart();state['phase']='rolled_back_config_only';write(STATE,state)
    print('Gateway restored to previous C config; ledger/grants untouched; C quarantine remains')

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=['prepare','activate','status','rollback']);args=parser.parse_args()
    if args.command=='prepare':prepare()
    elif args.command=='activate':activate()
    elif args.command=='rollback':rollback()
    else:
        _,_,g=policy();print(json.dumps({'gateway_mode':g['mode'],'b':request('/api/v1/voice-ab/b/status',optional=True)}))
