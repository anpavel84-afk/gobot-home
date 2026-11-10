"""Export audited legacy UI assets; no provider calls or service restarts."""
import sys,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'services/brain'))
from gobot.demo2 import prepare
if __name__=='__main__':
    result=prepare()
    print(json.dumps({'baseline':result['baseline'],'assets':len(result['files']),'provider_calls':0}))
