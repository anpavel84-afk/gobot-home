"""Small data-driven intent library. Exact matches + validated slots, no fuzzy actions."""
import json,re
from pathlib import Path
from functools import lru_cache
from dataclasses import dataclass
from .timer_duration import timer_seconds

@lru_cache(maxsize=1)
def library():return json.loads((Path(__file__).parents[1]/'quick-intents.json').read_text(encoding='utf8'))

@dataclass(frozen=True)
class QuickIntent:
    intent:str
    executor:str
    slots:dict

def normalize(text):
    value=' '.join(text.casefold().replace('ё','е').strip().rstrip('.!?').split())
    for _ in range(2):value=re.sub(r'^(?:гобот[, ]+|пожалуйста[, ]+|(?:скажи|подскажи)[, ]+пожалуйста[, ]+)','',value)
    return re.sub(r'[, ]+пожалуйста$','',value)

def match_quick(text):
    if len(text)>200:return None
    value=normalize(text)
    matches=[]
    for row in library()['entries']:
        if row['status']!='implemented':continue
        for pattern in row['patterns']:
            found=re.fullmatch(pattern,value)
            if found:
                slots=found.groupdict()
                if row['intent']=='timer_start':
                    if re.search(r'\bили\b',slots.get('duration') or ''):continue
                    slots['seconds']=timer_seconds(slots.get('duration') or '')
                matches.append((row.get('priority',0),QuickIntent(row['intent'],row['executor'],slots)));break
    best=max((priority for priority,_ in matches),default=0)
    unique={m.intent:m for priority,m in matches if priority==best}
    return next(iter(unique.values())) if len(unique)==1 else None
