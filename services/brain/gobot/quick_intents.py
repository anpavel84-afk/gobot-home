"""Small data-driven intent library. Exact matches + validated slots, no fuzzy actions."""
import json,re
from pathlib import Path
from functools import lru_cache
from dataclasses import dataclass
from .timer_duration import timer_seconds,is_timer_duration_reply
import time

@lru_cache(maxsize=1)
def library():return json.loads((Path(__file__).parents[1]/'quick-intents.json').read_text(encoding='utf8'))

@dataclass(frozen=True)
class QuickIntent:
    intent:str
    executor:str
    slots:dict
    status:str='validated'
    reason:str=''

def normalize(text):
    value=' '.join(text.casefold().replace('ё','е').strip().rstrip('.!?').split())
    for _ in range(2):value=re.sub(r'^(?:гобот[, ]+|пожалуйста[, ]+|(?:скажи|подскажи)[, ]+пожалуйста[, ]+)','',value)
    value=re.sub(r'^(?:ты можешь|можешь(?: ли)?(?: ты)?|не мог бы ты|не могли бы вы|давай(?: ка)?)[, ]+','',value)
    return re.sub(r'[, ]+пожалуйста$','',value)

def resolve_quick(text,context=None):
    if len(text)>200:return None
    value=normalize(text)
    from .quick_utilities import intent as utility_intent
    utility=utility_intent(value)
    if utility:
        if utility.get('operation')=='text':utility['text']=text.rsplit(': ',1)[-1].strip()
        return QuickIntent('utility_'+utility['operation'],'utility',utility)
    from .skill_catalogue import unavailable_request
    unavailable=unavailable_request(value,context)
    if unavailable:return QuickIntent('integration_unavailable','skill_readiness',unavailable,'unavailable')
    from .settings_tools import settings_intent
    setting=settings_intent(value,context)
    if setting:return QuickIntent('settings','settings',setting)
    # A polite refusal followed by an explicit new question is not a session end.
    value=re.sub(r'^нет[, ]+спасибо[, ]+(?:а\s+)?','',value)
    pending=(context or {}).get('pending_action')
    if pending and pending.get('kind')=='timer_duration' and pending.get('expires',0)>time.time() and is_timer_duration_reply(value):
        return QuickIntent('timer_start','timer',{'seconds':timer_seconds(value),'operation':'start'})
    matches=[]
    for row in library()['entries']:
        for pattern in row['patterns']:
            found=re.fullmatch(pattern,value)
            if found:
                slots=found.groupdict()
                status='validated' if row['status']=='implemented' else 'unavailable'
                executor=row['executor'] if status=='validated' else 'unavailable'
                if row['intent']=='timer_start':
                    slots['seconds']=timer_seconds(slots.get('duration') or '')
                    slots['operation']='start'
                    if slots['seconds'] is None:
                        status='needs_parameters' if not slots.get('duration') else 'rejected'
                        if status=='rejected':executor='quick_clarify'
                if row['intent']=='timer_cancel':
                    slots.update(operation='cancel',target=slots.get('target') or slots.get('after') or '')
                    if (slots.get('target') and slots.get('after')) or re.search(r'\b(?:и|или|не|либо)\b',slots['target']):
                        status='rejected';executor='quick_clarify'
                matches.append((row.get('priority',0),QuickIntent(row['intent'],executor,slots,status)));break
    best=max((priority for priority,_ in matches),default=0)
    unique={m.intent:m for priority,m in matches if priority==best}
    if len(unique)>1:return QuickIntent('ambiguous','quick_clarify',{},'rejected','multiple_intents')
    if unique:return next(iter(unique.values()))
    # Command-shaped but unsupported timer syntax is a clarification, never a
    # second permissive route into the executor. Questions are not commands.
    if re.match(r'^(?:(?:поставь|поставить|установи|установить|запусти|запустить|включи|включить|отмени|останови|выключи|убери)\b.*таймер|таймер\b|(?:засеки|засечь|засекай|отсчитай|отсчитать)\b)',value):
        return QuickIntent('timer_ambiguous','quick_clarify',{},'rejected','whole_command_not_validated')
    return None

def match_quick(text):
    """Compatibility view for the catalog/eval; routing uses resolve_quick once."""
    result=resolve_quick(text)
    return result if result and result.status in {'validated','needs_parameters'} else None
