"""Local operator staging of the approved ONE 180s manual B / ONE Sol High job.

Never calls a model. Stage -> guarded idle Brain deployment -> activate. Rollback
stages the previous mount and requires an idle Brain restart; ledgers stay intact.
"""
import argparse,json,shutil,sqlite3,sys
from datetime import datetime,timezone
from night_preview import ROOT,idle,write,request
from board_b_enable import gateway_restart,CONFIG,BROOT
sys.path.insert(0,str(ROOT/'services/brain'))
from gobot.board_trial import prepare_trial,TrialBudget,PublicExpertBudget

TRIAL=ROOT/'run/voice-ab-b-extended'
STATE=TRIAL/'deployment.json'

def stage():
    idle();g=json.loads(CONFIG.read_text());mount=BROOT/'mount.json'
    if STATE.exists():raise RuntimeError('trial_already_staged_no_renewal')
    assert g['mode']=='realtime_b' and request('/api/v1/voice-ab/b/status')['pending_hangups']==0
    folder=TRIAL/'backups'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ');folder.mkdir(parents=True)
    shutil.copy2(CONFIG,folder/'gateway.json');shutil.copy2(mount,folder/'mount.json')
    for name,root in [('original',BROOT),('extended',TRIAL),('expert',TRIAL/'experts')]:
        if (root/'usage.sqlite').exists():
            with sqlite3.connect((root/'usage.sqlite').as_uri()+'?mode=ro',uri=True) as src,sqlite3.connect(folder/(name+'.sqlite')) as dst:src.backup(dst)
    prepare_trial(TRIAL,g['device_id']);budget=TrialBudget(TRIAL);expert=PublicExpertBudget(TRIAL/'experts')
    assert budget.board_status()['sessions_remaining']==1 and not budget.pending_calls()
    assert expert.status()['sessions_reserved']==0 and expert.policy().allowed_client_id==g['device_id']
    write(STATE,{'backup':str(folder.relative_to(ROOT)),'phase':'staged','automatic_paid_calls':0})
    for b in (budget,expert):write(b.policy_path,{**b.policy().model_dump(),'enabled':True})
    write(mount,{'enabled':True,'profile':'extended'})
    print('Staged separate allowance. Requires guarded idle Brain deployment; no provider opened.')

def activate():
    idle();state=json.loads(STATE.read_text());assert state['phase']=='staged'
    status=request('/api/v1/voice-ab/b/status');g=json.loads(CONFIG.read_text())
    assert status['enabled'] and status['session_seconds']==180 and status['sessions_remaining']==1
    assert not status['pending_hangups'] and not status['active_sessions']
    write(CONFIG,{**g,'hardware_expert_consent':True});gateway_restart()
    write(STATE,{**state,'phase':'active_manual_only','runtime':request('/api/v1/status')['runtime_code_commit']})
    print(json.dumps({'manual_ready':True,'seconds':180,'one_public_sol_high':True,'automatic_paid_calls':0}))

def rollback():
    idle()
    if TrialBudget(TRIAL).pending_calls():raise RuntimeError('trial_close_unconfirmed_no_budget_switch')
    state=json.loads(STATE.read_text());folder=(ROOT/state['backup']).resolve()
    assert folder.is_relative_to(TRIAL/'backups')
    saved=json.loads((folder/'gateway.json').read_text());g=json.loads(CONFIG.read_text())
    assert saved['device_id']==g['device_id'] and saved['mode']=='realtime_b'
    # Block new trial starts before staging the previous mount. Never restore DBs.
    for b in (TrialBudget(TRIAL),PublicExpertBudget(TRIAL/'experts')):write(b.policy_path,{**b.policy().model_dump(),'enabled':False})
    write(CONFIG,saved);write(BROOT/'mount.json',json.loads((folder/'mount.json').read_text()))
    gateway_restart();write(STATE,{**state,'phase':'rollback_staged_brain_restart_required'})
    print('Previous B config staged. Perform guarded idle Brain restart. All ledgers preserved.')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['stage','activate','rollback','status']);a=p.parse_args()
    if a.command=='stage':stage()
    elif a.command=='activate':activate()
    elif a.command=='rollback':rollback()
    else:print(json.dumps(request('/api/v1/voice-ab/b/status')))
