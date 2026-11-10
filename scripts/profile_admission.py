"""Local metadata/hash benchmark only: no CLI process, provider request or auth copy."""
import json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
PROBE='''
import sys,time,json
sys.path.insert(0,'services/brain')
from gobot.live_agents import agent_status
start=time.perf_counter();agent_status(True);cold=(time.perf_counter()-start)*1000
# The same mandatory verification remains; only immutable hash entries are warm.
start=time.perf_counter();agent_status(True);warm=(time.perf_counter()-start)*1000
print(json.dumps({'unprimed_admission_ms':cold,'first_request_after_startup_priming_ms':warm}))
'''
samples=[]
for _ in range(4):
    result=subprocess.run([sys.executable,'-X','utf8','-c',PROBE],cwd=ROOT,capture_output=True,text=True,timeout=15,check=True)
    samples.append(json.loads(result.stdout))
sys.path.insert(0,str(ROOT/'services/brain'))
from gobot.telemetry import code_commit,fingerprint
report={'kind':'real local metadata/hash timings, not real provider latency','samples':samples,
        'source_head':code_commit(),'code_config_fingerprint':fingerprint(),
        'change':'Brain and Bridge lifespan prime metadata before readiness; per-request checks remain',
        'cli_spawns':0,'model_calls':0,'openai_calls':0,'overall_speech_improvement_measured':False,
        'p95':None,'note':'n=4 paired fresh-process observations; not a representative distribution'}
(ROOT/'docs/admission-profile-v02.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
print(json.dumps(report,indent=2))
