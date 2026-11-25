#!/usr/bin/env python3
"""Compare a real adapter's normalized trace; does not run or simulate GoBot."""
import argparse,json,sys,math
from pathlib import Path

def compare(expected,actual,path='$'):
    errors=[]
    if isinstance(expected,dict):
        if not isinstance(actual,dict):return [f'{path}: expected object, received {type(actual).__name__}']
        for key,value in expected.items():
            suffix=next((s for s in ('_lte','_max') if key.endswith(s)),None)
            if suffix and isinstance(value,(int,float)) and not isinstance(value,bool):
                metric=key[:-len(suffix)];got=actual.get(metric)
                if isinstance(got,bool) or not isinstance(got,(int,float)) or not math.isfinite(got) or got>value:
                    errors.append(f'{path}.{metric}: expected <= {value}, received {got!r}')
            elif key not in actual:errors.append(f'{path}.{key}: missing')
            else:errors.extend(compare(value,actual[key],f'{path}.{key}'))
    elif isinstance(expected,list):
        if not isinstance(actual,list) or len(expected)!=len(actual):return [f'{path}: expected exact list length {len(expected)}']
        for i,(e,a) in enumerate(zip(expected,actual)):errors.extend(compare(e,a,f'{path}[{i}]'))
    elif isinstance(expected,bool):
        if type(actual) is not bool or expected!=actual:errors.append(f'{path}: expected {expected!r}, received {actual!r}')
    elif isinstance(expected,(int,float)):
        if isinstance(actual,bool) or not isinstance(actual,(int,float)) or expected!=actual:errors.append(f'{path}: expected {expected!r}, received {actual!r}')
    elif expected!=actual:errors.append(f'{path}: expected {expected!r}, received {actual!r}')
    return errors

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('case_id');parser.add_argument('trace',type=Path)
    parser.add_argument('--cases',type=Path,default=Path(__file__).with_name('dialogue-cases.json'))
    args=parser.parse_args();cases=json.loads(args.cases.read_text(encoding='utf-8'))['cases']
    case=next((x for x in cases if x['id']==args.case_id),None)
    if case is None:parser.error('unknown case ID')
    trace=json.loads(args.trace.read_text(encoding='utf-8'));actual=trace.get('observed',trace)
    errors=compare(case['expected'],actual)
    print(json.dumps({'case_id':args.case_id,'structured_contract_match':not errors,'errors':errors,'semantic_audio_screen_verification':'separate_required','runtime_executed_by_this_checker':False},ensure_ascii=False,indent=2))
    return 1 if errors else 0
if __name__=='__main__':sys.exit(main())
