"""Public authored scenario inventory; never a source of permissions or tools."""
import json
from pathlib import Path
from functools import lru_cache
from collections import Counter

@lru_cache(maxsize=1)
def catalogue():
    path=Path(__file__).parents[1]/'assistant-skills.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'scenarios':[]}

def dialogue_instructions():
    """Reviewed product rules; this inventory never grants tool permissions."""
    return 'Домашние сценарии GoBot:\n'+'\n'.join('- '+row['instruction'] for row in catalogue().get('dialogue_rules',[]))

def summary():
    rows=catalogue()['scenarios']
    return {'scenarios':len(rows),'readiness':dict(Counter(r['readiness'] for r in rows)),
        'all_integrations_enabled':False,'acoustic_parity_verified':False,'inventory_is_not_permission':True}

def compact_instructions(query, *, intent=None, context=None, max_chars=1200, max_rules=4):
    """Only selected reviewed rules; never all cards, facts, or raw context."""
    from .behavior_library import select_rules
    return select_rules(query,intent=intent,context=context,max_chars=max_chars,max_rules=max_rules)['instructions']

def unavailable_request(value,context=None,*,registry=None):
    """Preserve exact mappings and guard bounded natural external commands.

    registry is an optional explicit server-owned Mapping/lookup whose values
    are installed callable handlers. Never read readiness flags from context.
    A registered handler must still pass Brain routing and ACL; it is not run here.
    """
    from .behavior_library import command_value,external_request,handler_registered,inventory_capability,unavailable_reason
    normalized=command_value(value)
    if normalized is None:return None
    candidate=None
    for row in catalogue()['scenarios']:
        if row['path']=='integration' and command_value(row['request'])==normalized:
            candidate={'category':row['category'],'capability':inventory_capability(row)}
            break
    if candidate is None:candidate=external_request(normalized)
    if candidate is None:return None
    category=candidate['category']
    # Existing A/private-memory paths remain untouched. C guest cannot claim them.
    if category=='private_and_scheduled' and not (context or {}).get('native_live_guest'):return None
    if handler_registered(registry,candidate['capability']):return None
    return {'operation':'unavailable','category':category,
        'capability':candidate['capability'],'reason':unavailable_reason(candidate['capability'])}

def unavailable_text(category):
    return {'timer_extended':'Имена, пауза и изменение длительности таймера пока не поддерживаются. Можно создать обычный таймер, узнать остаток или отменить его. Запрошенное изменение не выполнено.',
        'smart_home':'Интеграция умного дома пока не подключена: нужны выбранный контроллер и разрешённые устройства. Команда устройству не отправлена.',
        'connected_services':'Этот внешний сервис пока не подключён к GoBot. Нужны его серверный адаптер и доступ аккаунта; действие не выполнено.',
        'private_and_scheduled':'Этот персональный или отложенный сценарий пока не реализован либо требует отдельной проверки прав. Распознавание голоса не открывает приватные данные. Действие не выполнено.'}.get(category,'Эта интеграция пока не подключена. Действие не выполнено.')
