import argparse,sys
from pathlib import Path
r=Path(__file__).resolve().parents[1];sys.path.insert(0,str(r/'services/brain'))
from gobot.memory import Memory
p=argparse.ArgumentParser();p.add_argument('--conversation');p.add_argument('--forget-facts-for-device');p.add_argument('--confirm',action='store_true');a=p.parse_args()
if not a.confirm:p.error('Explicit --confirm required')
m=Memory(str(r/'data/gobot.sqlite'))
if a.conversation:m.purge(conversation=a.conversation)
if a.forget_facts_for_device:m.forget_facts(a.forget_facts_for_device)
print('Requested memory scope cleared')
