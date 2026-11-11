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

def unavailable_request(value,context=None):
    # Curated external operations must never fall through to invented completion.
    for row in catalogue()['scenarios']:
        if row['path']=='integration' and row['request'].casefold().replace('ё','е').rstrip('.!?')==value:
            category=row['category']
            if category=='private_and_scheduled' and not (context or {}).get('native_live_guest'):return None
            return {'operation':'unavailable','category':category}
    return None

def unavailable_text(category):
    return {'smart_home':'Интеграция умного дома пока не подключена: нужны выбранный контроллер и разрешённые устройства. Команда устройству не отправлена.',
        'connected_services':'Этот внешний сервис пока не подключён к GoBot. Нужны его серверный адаптер и доступ аккаунта; действие не выполнено.',
        'private_and_scheduled':'Этот персональный или отложенный сценарий пока не реализован либо требует отдельной проверки прав. Распознавание голоса не открывает приватные данные. Действие не выполнено.'}.get(category,'Эта интеграция пока не подключена. Действие не выполнено.')
