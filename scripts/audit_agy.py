"""Read-only native CLI commands; zero model turns/tokens required."""
import asyncio,hashlib,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'services/brain'))
from gobot.antigravity import argv,WORK,environment,POLICY,binary
from gobot.processes import native_process
from gobot.antigravity_login import authenticated
async def command(name):
    settings=json.loads(POLICY.read_text());settings['disableSlashCommands']=False
    launch=argv(stream=False);launch[launch.index('--settings')+1]=json.dumps(settings)
    launch+=['--print',name,'--output-format','json','--print-timeout','10s']
    async with native_process(launch,WORK,environment(),discard_errors=False) as process:
        out,err=await asyncio.wait_for(process.communicate(),20)
        if process.returncode:raise RuntimeError('read-only agy audit failed; raw output withheld')
        obj=json.loads(out)
        if obj.get('num_turns')!=0 or obj.get('usage',{}).get('total_tokens')!=0:raise RuntimeError('audit unexpectedly reported model usage')
        return obj
async def main():
    result=await command('/permissions')
    entries=result['command']['data']['permissions'];denied=set()
    for entry in entries:denied.update(entry.get('deny',[]))
    required=set(json.loads(POLICY.read_text())['permissions']['deny'])
    report={'oauth_authenticated':await authenticated(),'deny_verified':required<=denied,
            'effective_deny_rules':sorted(denied),'policy_sha256':hashlib.sha256(POLICY.read_bytes()).hexdigest(),
            'binary_sha256':hashlib.sha256(binary().read_bytes()).hexdigest(),
            'adapter_sha256':hashlib.sha256((ROOT/'services/brain/gobot/antigravity.py').read_bytes()).hexdigest(),
            'read_only_command':'/permissions','model_turns':0,'model_tokens':0,'checked':time.time(),
            'live_response_verified':False,'notes':'Effective native permission report; not an adversarial model/tool execution test.'}
    (ROOT/'run/antigravity-audit.json').write_text(json.dumps(report,indent=2))
    (ROOT/'docs/antigravity-audit.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))
if __name__=='__main__':asyncio.run(main())
