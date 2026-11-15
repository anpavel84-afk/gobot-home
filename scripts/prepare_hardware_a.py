"""Prepare a DISABLED proposed A allowance. Owner approval required to enable.

Never invokes CLI/STT/TTS or renews a previous grant. Does not alter B/C ledgers.
"""
import json,sys,time
from pathlib import Path
from uuid import uuid4
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'services/brain'))
from gobot.expert_store import ExpertPolicy

def prepare(root,client):
    root=Path(root);root.mkdir(parents=True,exist_ok=True);path=root/'policy.json'
    if path.exists():return path
    p=ExpertPolicy(enabled=False,authorization=uuid4().hex,audience='owner_interactive',
        allowed_client_id=client,expires_at=time.time()+86400,max_sessions=2,allowed_profiles=['SOL_HIGH'],
        job_timeout_seconds=90,max_context_tokens=3000,max_result_characters=6000)
    with path.open('x',encoding='utf8') as out:out.write(p.model_dump_json(indent=2))
    return path

if __name__=='__main__':
    g=json.loads((ROOT/'data/hardware/gobot-v1/gateway.json').read_text())
    path=prepare(ROOT/'run/hardware-a',g['device_id'])
    print(json.dumps({'prepared':True,'enabled':False,'path':str(path.relative_to(ROOT)),
        'cli_profile':'SOL_HIGH','max_a_turns':2,'max_cli_seconds_each':90,
        'tts_characters_each':3000,'followup_recording_seconds_each':26,'automatic_paid_calls':0}))
