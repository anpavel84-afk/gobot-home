"""Offline policy labels only; never calls providers or estimates model correctness."""
import json,time,statistics,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'services/brain'))
from gobot.routing import SmartRouter
from gobot.models import ChatRequest
def main():
    cases=json.loads((ROOT/'tests/fixtures/quality-router.json').read_text(encoding='utf-8'))['cases'];router=SmartRouter();times=[];failures=[];routes={}
    for case in cases:
        req=ChatRequest(text=case['text'],mode='auto',usage_consent=True);start=time.perf_counter()
        d=router.choose(req,case['context'],{'antigravity':{'available':True},'codex':{'available':True}});times.append((time.perf_counter()-start)*1000)
        label=d.tool or ('codex' if d.provider=='codex' else 'argon' if 'argon' in (d.model or '') else 'reasoning' if d.category=='REASONING' else 'flash')
        routes[label]=routes.get(label,0)+1
        if label!=case['expected'] or d.quality['verification_required']!=case['verification_required']:failures.append(case['id'])
    result={'synthetic':True,'cases':len(cases),'unique_queries':len({c['text'] for c in cases}),'routing_labels_passed':len(cases)-len(failures),'failures':failures,'distribution':routes,'router_ms':{'p50':statistics.median(times),'p95':sorted(times)[int(len(times)*.95)-1]},'classifier_model_calls':0,'total_model_calls':0,'api_cost':0,'cli_quota_used':0,'actual_model_correctness':None,'unsupported_claim_rate':None,'comparative_quality':'not measured; no paid inference permitted for evaluation','lite_approved_categories':[]}
    (ROOT/'docs/router-evaluation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
