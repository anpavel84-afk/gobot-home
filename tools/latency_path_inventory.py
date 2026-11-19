"""Read-only actual PLAN L0 inventory. No paid endpoints or microphone.
Records allowlisted configuration and source hashes, never secrets or dialogue.
Run in existing Brain venv; output is an explicit optional local report.
"""
import argparse, hashlib, json, sys
from pathlib import Path
import httpx

FILES=['services/voice/gobot_device_gateway.py','services/voice/spotpear_realtime.py',
       'services/voice/spotpear_live.py','services/voice/spotpear_livekit.py',
       'services/voice/spotpear_half_duplex.py','services/brain/gobot/realtime_contract.py',
       'services/phone/dist/realtime.js']

def audit(root, output):
    root=Path(root).resolve()
    config=json.loads((root/'data/hardware/gobot-v1/gateway.json').read_text(encoding='utf8'))
    state=json.loads((root/'data/hardware/gobot-v1/gateway-status.json').read_text(encoding='utf8'))
    token=json.loads((root/'run/keys.json').read_text(encoding='utf8'))['api_token']
    results={}
    with httpx.Client(trust_env=False,timeout=10) as client:
        for name,endpoint in [('brain','/api/v1/status'),('board_b','/api/v1/voice-ab/b/status'),('web_b','/api/v1/realtime/status')]:
            r=client.get('http://127.0.0.1:18781'+endpoint,headers={'Authorization':'Bearer '+token})
            r.raise_for_status(); obj=r.json()
            fields={'brain':['runtime_code_commit','active_turns','active_voice_streams'],
                    'board_b':['enabled','model','voice','sessions_remaining','session_seconds','active_sessions','pending_hangups','admission_reason'],
                    'web_b':['enabled','model','voice','sessions_remaining','active_sessions','admission_reason']}[name]
            results[name]={k:obj[k] for k in fields if k in obj}
    fields=['mode','continuous_live','hardware_realtime_consent','hardware_live_consent']
    result={'read_only':True,'paid_calls':0,'runtime_switched':False,
            'gateway':{k:config.get(k) for k in fields},
            'gateway_active':state.get('active'),
            'gateway_stored_setup_ms':state.get('last_setup_ms'),
            'setup_evidence':'historical numeric last-session observation, not a new test',
            'services':results,'source_sha256':{}}
    for name in FILES:
        p=root/name
        if p.is_file():
            with p.open('rb') as f:result['source_sha256'][name]=hashlib.file_digest(f,'sha256').hexdigest()
    Path(output).write_text(json.dumps(result,indent=2),encoding='utf8')
    print(json.dumps(result),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--output',required=True);a=p.parse_args();audit(a.root,a.output)
