"""Read-only private HTTPS + bounded existing Open-Meteo smoke. No model calls.

Only opens RAM hybrid conversations, asks clock/weather, verifies protected routes
and compares financial/policy contents with the pre-deployment WAL backups.
"""
import hashlib,json,sqlite3,sys
from pathlib import Path
import httpx
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'services/brain'))

def digest_rows(path):
    with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:
        tables=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        values=[(t,sorted(db.execute('SELECT * FROM "'+t.replace('"','""')+'"').fetchall(),key=repr)) for t in tables]
    return hashlib.sha256(repr(values).encode()).hexdigest()

def main():
    deployment=json.loads((ROOT/'run/night-train/deployment.json').read_text());backup=ROOT/deployment['backup']
    result={'runtime':deployment['runtime'],'url':deployment['url'],'paid_calls_requested':0,'routes':{},'financial_tables_unchanged':{},'financial_policies_unchanged':{}}
    origin='https://plan.tailffc57c.ts.net:18786'
    with httpx.Client(trust_env=False,verify=str(ROOT/'run/tls/gobot.crt'),timeout=20,headers={'Origin':origin}) as browser:
        for path in ['/device-next','/device','/demo2','/device-next.js','/story-player.js']:
            response=browser.get(origin+path);result['routes'][path]=response.status_code;assert response.status_code==200
        status=browser.get(origin+'/api/next/status').json();assert status['enabled'] and not status['fixture_mode']
        assert status['runtime_sha']==deployment['runtime']
        def post(path,body):
            response=browser.post(origin+'/api/next/'+path,json=body);response.raise_for_status();return response.json()
        conversation=post('open',{})['conversation_id'];op=post('operation',{'conversation_id':conversation})['operation_id']
        clock=post('dispatch',{'input':{'conversation_id':conversation,'operation_id':op,'text':'Который час?'}})
        assert clock['approved'] and clock['results'][0]['status']=='success'
        result['private_https_clock']='verified_local_tool'
        assert browser.post(origin+'/api/next/open',json={'role':'owner'}).status_code==422
        result['client_authority_rejected']=True
        foreign=browser.get(origin+'/device-next',headers={'Host':'invalid.example'});assert foreign.status_code==403
        result['foreign_host_denied']=True
    # Home weather uses the existing bound phone device profile; never publish place/coordinates.
    token=json.loads((ROOT/'run/keys.json').read_text())['api_token']
    policy=json.loads((ROOT/'run/owner-testing/policy.json').read_text())
    scope={'principal':'browser-100-120-201-115','client_id':policy['allowed_client_id'],'binding':policy['allowed_client_id'],'profile_epoch':None}
    with httpx.Client(trust_env=False,timeout=25,headers={'Authorization':'Bearer '+token}) as brain:
        def local(path,body):
            response=brain.post('http://127.0.0.1:18781/api/v1/next/'+path,json={**body,**scope});response.raise_for_status();return response.json()
        conversation=local('open',{})['conversation_id'];answers=[]
        for text in ['Какая погода завтра?','А в субботу?']:
            op=local('operation',{'conversation_id':conversation})['operation_id']
            d=local('dispatch',{'input':{'conversation_id':conversation,'operation_id':op,'text':text}})
            answers.append({'route':d['route_type'],'statuses':[r['status'] for r in d['results']],'source':d['answer']['source']})
        result['real_weather']=answers
        main=brain.get('http://127.0.0.1:18781/api/v1/status').json()
        b=brain.get('http://127.0.0.1:18781/api/v1/realtime/status').json()
        c=brain.get('http://127.0.0.1:18781/api/v1/live/status').json()
        result['active']={'turns':main['active_turns'],'voice':main['active_voice_streams'],'b':b['active_sessions'],'c':c['active_sessions']}
        assert not any(result['active'].values())
        result['c_pending_count']=c['billing']['unconfirmed_sessions'];result['c_unknown_reserve_seconds']=c['billing']['unknown_final_usage_reserve_seconds']
    for n,name in enumerate(('live','realtime','owner-testing'),1):
        result['financial_tables_unchanged'][name]=digest_rows(ROOT/f'run/{name}/usage.sqlite')==digest_rows(backup/f'db-{n}.sqlite')
        namepath=Path(f'run/{name}/policy.json');current=ROOT/namepath;old=backup/namepath
        result['financial_policies_unchanged'][name]=(current.read_bytes() if current.exists() else None)==(old.read_bytes() if old.exists() else None)
    assert all(result['financial_tables_unchanged'].values()) and all(result['financial_policies_unchanged'].values())
    (ROOT/'run/night-train/private-smoke.json').write_text(json.dumps(result,indent=2),encoding='utf8');print(json.dumps(result))
if __name__=='__main__':main()
