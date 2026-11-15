#!/usr/bin/env python3
"""Validate authored files and provenance. Never calls a model or GoBot runtime."""
from pathlib import Path
from collections import Counter
from datetime import datetime
import json,sys,hashlib

ROOT=Path(__file__).resolve().parent
def main():
    errors=[]
    def require(condition,message):
        if not condition:errors.append(message)
    def read(name):return json.loads((ROOT/name).read_text(encoding='utf-8'))
    source=read('source-inventory.json')['scenarios'];catalog=read('scenario-library.json')['scenarios'];cases=read('dialogue-cases.json')['cases'];fixtures=read('fixtures.json')['fixtures'];schema=read('scenario.schema.json')
    require(len(source)==400,'source inventory size !=400');require(len(catalog)==400,'enriched inventory size !=400');require(len(cases)==120,'dialogue case count !=120')
    original={s['id']:s for s in source};ids=[s['id'] for s in catalog]
    require(len(set(ids))==len(ids),'duplicate inventory IDs');require(set(ids)==set(original),'inventory IDs changed')
    routes=set(schema['properties']['route']['enum']);states=set(schema['properties']['capability_status']['enum'])
    for s in catalog:
        sid=s.get('id','<missing>')
        require(set(schema['required']).issubset(s),f'{sid}: required fields missing')
        require(not(set(s)-set(schema['properties'])),f'{sid}: unexpected keys')
        require(s.get('category')==original.get(sid,{}).get('category'),f'{sid}: category changed')
        u=s.get('utterances',[]);r=s.get('response_variants',[])
        require(len(u)>=3 and len(set(u))==len(u),f'{sid}: missing/duplicate paraphrases')
        require(bool(u) and u[0]==original.get(sid,{}).get('request'),f'{sid}: canonical request changed')
        require(len(r)>=2 and all(isinstance(x,str) and x.strip() for x in r),f'{sid}: response variants missing')
        require(s.get('route') in routes,f'{sid}: unknown route')
        require(s.get('capability_status') in states,f'{sid}: unknown capability state')
        require(s.get('priority') in ['P0','P1','P2'],f'{sid}: invalid priority')
        require(isinstance(s.get('slots'),dict),f'{sid}: slots must be object')
        for key in ['preconditions','expected_behavior','forbidden','acceptance']:
            v=s.get(key);require(isinstance(v,list) and len(v)>0 and all(isinstance(x,str) and x.strip() for x in v),f'{sid}: invalid {key}')
        require(s.get('failure',{}).get('forbid_success') is True,f'{sid}: failure success guard absent')
        require(s.get('execution_evidence')=={'offline':'not_run','provider':'not_run','acoustic':'not_run'},f'{sid}: spec falsely marked as executed')
    cids=[c['id'] for c in cases];require(len(set(cids))==len(cids),'duplicate dialogue case IDs')
    require(sum(c['id'].startswith('W') for c in cases)==74,'weather case count !=74')
    known={f['id'] for f in fixtures};base=fixtures[0]
    for c in cases:
        cid=c['id'];require(c.get('fixture') in known,f'{cid}: missing fixture');require(bool(c.get('turns')) and bool(c.get('expected')),f'{cid}: missing turns/expectation')
        require(c.get('execution_evidence')=={'offline':'not_run','provider':'not_run','acoustic':'not_run'},f'{cid}: false test execution claim')
        for t in c.get('turns',[]):require(bool(t.get('event')),f'{cid}: event missing')
        g=c.get('given_overrides',{});clock=datetime.fromisoformat(g.get('clock_utc',base['clock_utc']).replace('Z','+00:00'))
        if 'clock_utc' in g:
            payload=g.get('weather_fixture',{});fetched=payload.get('fetched_at')
            require(bool(fetched),f'{cid}: clock change lacks fresh payload timestamp')
            if fetched:require(0<=(clock-datetime.fromisoformat(fetched.replace('Z','+00:00'))).total_seconds()<=60,f'{cid}: stale/future shifted payload')
        caps={**base.get('capabilities',{}),**g.get('capabilities',{})}
        if caps.get('alarm_recurrence') or caps.get('alarm_snooze'):require(caps.get('alarm') is True,f'{cid}: subcapability without alarm')
    require(len(read('dialogue-rules.json')['rules'])==36,'rule count changed')
    optional_schema_validation='not_available_stdlib_checks_only'
    try:
        import jsonschema
        for s in catalog:
            try:jsonschema.validate(s,schema)
            except jsonschema.ValidationError as exc:errors.append(s['id']+': '+exc.message)
        cs=read('dialogue-case.schema.json')
        for c in cases:
            try:jsonschema.validate(c,cs)
            except jsonschema.ValidationError as exc:errors.append(c['id']+': '+exc.message)
        optional_schema_validation='completed'
    except ImportError:pass
    report={'artifact_validation_passed':not errors,'inventory_cases':len(catalog),'dialogue_cases':len(cases),'total_records':len(catalog)+len(cases),'weather_context_cases':74,'utterance_examples':sum(len(x['utterances']) for x in catalog),'response_examples':sum(len(x['response_variants']) for x in catalog),'category_counts':dict(Counter(s['category'] for s in catalog)),'capability_status_counts':dict(Counter(s['capability_status'] for s in catalog)),'schema_validation':optional_schema_validation,'source_ids_preserved':set(ids)==set(original),'errors':errors,'runtime_tests_executed':False,'paid_provider_calls':0,'iphone_acoustic_verified':False,'hardware_verified':False}
    (ROOT/'VALIDATION.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2));return 0 if not errors else 1
if __name__=='__main__':sys.exit(main())
