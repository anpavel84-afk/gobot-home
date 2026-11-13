"""Reviewed, bounded behavior selection and non-executing integration guards.

The companion contains aliases and small domain rules, never fixture values,
answers, credentials or executable capabilities. A registry is server-owned:
it maps a capability name to an actually registered callable handler, or is a
lookup callable returning that handler. Boolean/catalogue readiness is not a
handler. Finding one here never authorizes or executes it; Brain still owns ACL.
"""
from collections.abc import Mapping
from functools import lru_cache
import json
from pathlib import Path
import re


MAX_RULE_CHARS = 1200
MAX_RULES = 4
_ROOT = Path(__file__).parents[1]
_DOMAINS = frozenset({
    'weather', 'timers', 'smart_home', 'connected_services',
    'private_and_scheduled', 'language', 'learning', 'science', 'cooking',
    'gardening', 'home_advice', 'technical_explanations', 'writing',
    'planning', 'games', 'visuals', 'experts', 'device_settings',
    'local_utilities', 'time_and_control',
})
_FALLBACK_RULES = (
    {'id': 'base.truth', 'domain': 'general', 'instruction':
     'Luna не исполняет инструменты. Подтверждай действие только по результату '
     'Brain; цитаты, обсуждение и отрицания не являются командой.'},
    {'id': 'base.scope', 'domain': 'general', 'instruction':
     'Соблюдай текущие права, scope и лимиты; не вызывай другие модели и не '
     'повторяй действия автоматически. Каталог не даёт доступ.'},
)


def _normal(value):
    if not isinstance(value, str):
        return ''
    return ' '.join(value.casefold().replace('ё', 'е').strip().rstrip('.!?').split())


def validate_library(data, inventory):
    """Validate a projection against the authoritative, unchanged inventory."""
    if (not isinstance(data, dict) or type(data.get('schema_version')) is not int
            or data['schema_version'] != 1
            or data.get('kind') != 'reviewed_behavior_projection_not_runtime_grants'
            or data.get('not_a_capability_grant') is not True):
        raise ValueError('behavior_library_schema')
    if not isinstance(inventory, list):
        raise ValueError('behavior_inventory_schema')
    original = {row['id']: row for row in inventory}
    rows, rules = data.get('scenarios'), data.get('rules')
    if not isinstance(rows, list) or len(rows) != len(original):
        raise ValueError('behavior_inventory_mismatch')
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'id', 'domain', 'target_intent', 'utterances'}:
            raise ValueError('behavior_scenario_fields')
        sid, domain, utterances = row['id'], row['domain'], row['utterances']
        if (not isinstance(sid, str) or sid in seen or sid not in original
                or domain not in _DOMAINS or domain != original[sid]['category']
                or not isinstance(row['target_intent'], str)
                or not 1 <= len(row['target_intent']) <= 100
                or not isinstance(utterances, list) or not 1 <= len(utterances) <= 3
                or any(not isinstance(t, str) or not 1 <= len(t) <= 400 for t in utterances)
                or utterances[0] != original[sid]['request']):
            raise ValueError('behavior_scenario_invalid')
        seen.add(sid)
    if seen != set(original) or not isinstance(rules, list) or not 2 <= len(rules) <= 64:
        raise ValueError('behavior_rules_schema')
    seen_rules = set()
    for rule in rules:
        if (not isinstance(rule, dict) or set(rule) != {'id', 'domain', 'instruction'}
                or not isinstance(rule['id'], str) or not 1 <= len(rule['id']) <= 80
                or rule['id'] in seen_rules or rule['domain'] not in _DOMAINS | {'general'}
                or not isinstance(rule['instruction'], str)
                or not 1 <= len(rule['instruction']) <= 500):
            raise ValueError('behavior_rule_invalid')
        seen_rules.add(rule['id'])
    for base in _FALLBACK_RULES:
        if not any(rule == base for rule in rules):
            raise ValueError('behavior_base_rule_missing')
    if {r['domain'] for r in rules} != _DOMAINS | {'general'}:
        raise ValueError('behavior_domain_missing')
    return data


def load_library(path=None):
    path = Path(path) if path is not None else _ROOT / 'behavior-library.json'
    if path.stat().st_size > 512_000:
        raise ValueError('behavior_library_size')
    data = json.loads(path.read_text(encoding='utf-8'))
    inventory = json.loads((_ROOT / 'assistant-skills.json').read_text(encoding='utf-8'))['scenarios']
    return validate_library(data, inventory)


@lru_cache(maxsize=1)
def _runtime_library():
    return load_library()


def _intent_domain(intent):
    if not isinstance(intent, str):
        return None
    if intent in _DOMAINS:
        return intent
    prefixes = (
        ('weather', 'weather'), ('timer', 'timers'), ('clock', 'time_and_control'),
        ('utility', 'local_utilities'), ('settings', 'device_settings'),
        ('expert', 'experts'), ('visual', 'visuals'),
    )
    for prefix, domain in prefixes:
        if intent == prefix or intent.startswith((prefix + '_', prefix + '.')):
            return domain
    head = intent.split('.', 1)[0]
    return head if head in _DOMAINS else None


_FOLLOWUP = re.compile(
    r'(?:а |нет[, ]+)?(?:завтра|сегодня|послезавтра|ветер|влажность|давление|осадки|'
    r'там же|на неделю|подробнее|еще пример|повтори|почему|да|нет|\d{1,5})'
)
_DOMAIN_WORDS = (
    ('language', r'\b(?:переведи|перевод|произнести|произносится|антоним|синоним|рифм\w*|грамматик\w*)\b'),
    ('learning', r'\b(?:квиз|упражнен\w*|таблиц\w* умножения|научи|учебн\w*|потренируй)\b'),
    ('technical_explanations', r'\b(?:dns|sqlite|http|https|tls|webrtc|json|csv|pwm|шим|кэш|транзакци\w*|идемпотент\w*|тайм.?аут)\b'),
    ('science', r'^(?:почему|как устроен\w*|как работает|что такое)\b'),
    ('weather', r'\b(?:погод\w*|прогноз\w*|ветер|дожд\w*|осадк\w*|температур\w*)\b'),
    ('timers', r'\b(?:таймер\w*|засеки|засечь|отсчитай)\b'),
    ('private_and_scheduled', r'\b(?:напомни|напоминан\w*|будильник\w*|личн\w* заметк\w*|паспорт)\b'),
    ('connected_services', r'\b(?:музык\w*|песн\w*|плейлист\w*|радио|календар\w*|почт\w*|новост\w*)\b'),
    ('smart_home', r'\b(?:свет|ламп\w*|штор\w*|термостат\w*|розетк\w*|кондиционер\w*|пылесос\w*)\b'),
    ('cooking', r'\b(?:приготов\w*|рецепт\w*|сварить|омлет|рис|суп|специ\w*|тесто)\b'),
    ('gardening', r'\b(?:рассад\w*|огород\w*|грунт\w*|томат\w*|черен\w*|мульч\w*|дренаж)\b'),
    ('home_advice', r'\b(?:уборк\w*|хранени\w*|упакова\w*|холодильник\w*|расходник\w*)\b'),
    ('writing', r'\b(?:напиши|перефразируй|сочини|черновик)\b'),
    ('planning', r'\b(?:план|распланируй|расписание дня)\b'),
    ('games', r'\b(?:поиграем|поиграй|загадк\w*|игру|игра)\b'),
    ('visuals', r'\b(?:покажи|изображени\w*|картинк\w*|нарисуй)\b'),
    ('experts', r'\b(?:эксперт\w*|cli)\b'),
    ('time_and_control', r'\b(?:который час|дата|день недели|стоп)\b'),
    ('device_settings', r'\b(?:настройк\w*|громкость|язык устройства)\b'),
)


def select_rules(query, *, intent=None, context=None, max_chars=MAX_RULE_CHARS, max_rules=MAX_RULES):
    """Return only reviewed rules; never copy query, context, cards or fixtures.

    ``intent`` and ``context['active_intent']`` must be server-resolved and scoped.
    Context is used only for bounded short followups, never for new topics. The
    selector is advisory, not an action parser and not an authorization decision.
    """
    budget = max(0, min(MAX_RULE_CHARS, max_chars)) if type(max_chars) is int else MAX_RULE_CHARS
    count = max(0, min(MAX_RULES, max_rules)) if type(max_rules) is int else MAX_RULES
    value = _normal(query)[:1000]
    domain, available = None, True
    try:
        library = _runtime_library()
    except (OSError, ValueError, KeyError, TypeError):
        library = {'scenarios': [], 'rules': list(_FALLBACK_RULES)}
        available = False
    for row in library['scenarios']:
        if any(value == _normal(text) for text in row['utterances']):
            domain = row['domain']
            break
    if domain is None:
        # An explicit server-resolved intent is current; arbitrary user strings
        # never become instructions even if they happen to look like an intent.
        domain = _intent_domain(intent)
    if domain is None and _FOLLOWUP.fullmatch(value) and isinstance(context, Mapping):
        domain = _intent_domain(context.get('active_intent'))
    if domain is None:
        domain = next((d for d, pattern in _DOMAIN_WORDS if re.search(pattern, value)), 'general')
    candidates = [r for r in library['rules'] if r['domain'] == 'general']
    candidates += [r for r in library['rules'] if r['domain'] == domain and domain != 'general']
    selected, text = [], ''
    for rule in candidates:
        addition = ('\n' if text else '') + '- ' + rule['instruction']
        if len(selected) >= count:
            break
        if len(text) + len(addition) <= budget:
            text += addition
            selected.append(rule['id'])
    return {'schema_version': 1, 'domain': domain, 'rule_ids': selected,
            'instructions': text, 'library_available': available}


def handler_registered(registry, capability):
    """Lookup only. Explicit Mapping/callable returns a handler, never a bool.

    Do not pass a browser payload, fixture capabilities, or catalogue metadata.
    No absent/default external adapter is considered available. A registered
    handler still requires Brain's normal routing, slot validation and ACL.
    """
    if registry is None:
        return False
    try:
        handler = registry(capability) if callable(registry) else registry.get(capability) if isinstance(registry, Mapping) else None
    except Exception:
        # A failing readiness lookup cannot turn an absent adapter into a live
        # capability. The caller remains on the honest unavailable route.
        return False
    return callable(handler)


def inventory_capability(row):
    """Stable server capability keys for existing exact integration mappings."""
    category = row['category']
    if category == 'smart_home':
        return 'smart_home'
    index = int(row['id'].rsplit('-', 1)[-1])
    keys = {
        'connected_services': (
            'music', 'music', 'music', 'music', 'media', 'news', 'exchange_rates',
            'flight_schedule', 'space_schedule', 'taxi', 'shopping', 'delivery',
            'communications', 'communications', 'find_phone', 'navigation',
            'traffic', 'transit_schedule', 'mail', 'calendar',
        ),
        'private_and_scheduled': (
            'reminders', 'alarms', 'reminders', 'persistent_lists', 'private_memory',
            'private_memory', 'private_memory', 'private_memory', 'identity',
            'identity', 'identity', 'wake_word', 'communications', 'payments',
            'ticket_booking', 'scheduled_smart_home', 'scheduled_music',
            'audio_recording', 'private_memory', 'system_files',
        ),
    }
    values = keys.get(category, ())
    return values[index - 1] if 1 <= index <= len(values) else category


def unavailable_reason(capability):
    """Stable diagnostic codes; no human answer is inferred from a fixture."""
    return {
        'timer_named': 'named_timer_not_implemented',
        'timer_pause_resume': 'timer_pause_resume_not_implemented',
        'timer_extend': 'timer_extend_not_implemented',
        'timer_restart': 'timer_restart_not_implemented',
        'private_memory': 'private_memory_not_authorized',
        'identity': 'identity_scope_restricted',
        'system_files': 'system_file_access_not_authorized',
    }.get(capability, capability + '_not_connected')


_TAIL = r"[а-яa-z0-9][а-яa-z0-9 _.,:'’\-]{0,100}"
_OPTIONAL_TAIL = r'(?: ' + _TAIL + r')?'
# These expressions detect a bounded *unavailable* request only. They never
# produce executable arguments, handlers, approvals, or a new permissive path.
_GUARDS = (
    ('timer_extended', 'timer_pause_resume', (
        r'(?:поставь|поставить|переведи) таймер на паузу',
        r'(?:приостанови|приостановить|возобнови|возобновить|продолжи) (?:этот |мой )?таймер' + _OPTIONAL_TAIL,
    )),
    ('timer_extended', 'timer_restart', (
        r'перезапусти (?:этот |мой )?таймер' + _OPTIONAL_TAIL,
    )),
    ('timer_extended', 'timer_extend', (
        r'(?:продли|продлить) (?:этот |мой )?таймер' + _OPTIONAL_TAIL,
        r'(?:добавь|прибавь|убавь|вычти) (?:к таймеру |у таймера |таймеру )' + _TAIL,
        r'(?:добавь|прибавь|убавь) ' + _TAIL + r' (?:к таймеру|на таймере)',
    )),
    ('timer_extended', 'timer_named', (
        r'переименуй (?:этот |мой )?таймер' + _OPTIONAL_TAIL,
        r'(?:поставь|поставить|запусти|установи) (?:именованный )?таймер (?:для|с названием|под названием|по имени) ' + _TAIL,
        r'(?:поставь|поставить|запусти|установи) таймер на [а-я0-9 ,.-]{1,50} (?:с названием|под названием|для) ' + _TAIL,
        r'(?:поставь|поставить|запусти|установи) таймер (?!на\b)[а-яa-z][а-яa-z0-9 _-]{0,35} на [а-я0-9 ,.-]{1,50}',
    )),
    ('smart_home', 'smart_home', (
        r'(?:включи|включить|отключи|отключить|выключи|выключить|вруби|выруби|зажги|погаси) (?:весь |все |всю |мою |мой |эту |этот )?(?:свет|освещение|лампу|лампочку|лампы|люстру|подсветку|розетку|розетки|вентилятор|кондиционер|обогреватель|очиститель воздуха|устройства умного дома)' + _OPTIONAL_TAIL,
        r'(?:сделай|сделать) (?:свет|освещение|лампу) (?:ярче|тусклее|теплее|холоднее)' + _OPTIONAL_TAIL,
        r'(?:сделай|сделать) (?:ярче|тусклее|теплее|холоднее) (?:свет|освещение|лампу)' + _OPTIONAL_TAIL,
        r'(?:уменьши|увеличь|убавь|прибавь|установи) яркость(?: (?:лампы|света))?' + _OPTIONAL_TAIL,
        r'(?:открой|открыть|закрой|закрыть|прикрой|подними|опусти) (?:шторы|жалюзи|дверь|входную дверь|умный замок|ворота)' + _OPTIONAL_TAIL,
        r'(?:поставь|установи|переключи) (?:термостат|кондиционер) на ' + _TAIL,
        r'(?:запусти|останови|включи|выключи|отправь) (?:робот-пылесос|робот пылесос|пылесос)' + _OPTIONAL_TAIL,
        r'(?:покажи|проверь|проверить) (?:камеру|датчик протечки|влажность|качество воздуха)' + _OPTIONAL_TAIL,
        r'(?:запусти|запустить) сценарий ' + _TAIL,
    )),
    ('connected_services', 'music', (
        r'(?:включи|включить|поставь|поставить|запусти|запустить|вруби|послушаем) (?:любимую |спокойную |бодрую |какую-нибудь |мне )?(?:музыку|песню|трек|альбом|плейлист|радио|джаз|рок|классику)' + _OPTIONAL_TAIL,
        r'(?:поставь|включи|запусти) что(?:-| )нибудь (?:бодрое|спокойное|веселое|тихое|для сна|расслабляющее)',
        r'(?:хочу|хочется) послушать (?:музыку|песню|радио|джаз)' + _OPTIONAL_TAIL,
        r'(?:останови|выключи|приостанови|продолжи|возобнови) (?:музыку|песню|трек|радио|плейлист)' + _OPTIONAL_TAIL,
        r'(?:поставь|поставить) (?:музыку|песню|трек) на паузу',
        r'(?:включи|поставь|переключи на) (?:следующую|предыдущую) (?:песню|музыку|композицию)',
        r'(?:включи|поставь|переключи на) (?:следующий|предыдущий) трек',
    )),
    ('connected_services', 'calendar', (
        r'(?:создай|создать|добавь|добавить|запиши|запланируй|перенеси|отмени|удали) (?:встречу|событие|мероприятие)' + _OPTIONAL_TAIL,
        r'(?:добавь|запиши|внеси) (?:в мой календарь|в календарь) ' + _TAIL,
        r'(?:покажи|прочитай|проверь|открой) (?:мой |мои )?(?:календарь|встречи|события календаря)' + _OPTIONAL_TAIL,
        r'что (?:у меня )?в календаре' + _OPTIONAL_TAIL,
    )),
    ('private_and_scheduled', 'reminders', (
        r'(?:создай|создать|поставь|поставить|добавь|добавить|отмени|удали|покажи|повторяй|перенеси) (?:мне |мое |мои )?напоминани[ея]' + _OPTIONAL_TAIL,
        r'напомни(?: мне)? (?:завтра|послезавтра|сегодня|через|в|каждый|каждую|на следующей неделе) ' + _TAIL,
        r'напомни(?: мне)? (?:купить|позвонить|полить|забрать|выключить|проверить|вынести|сходить|записаться|отправить|оплатить) ' + _TAIL,
        r'напомни(?: мне)? о (?:встрече|созвоне|покупке|занятии|записи|приеме)' + _OPTIONAL_TAIL,
    )),
    ('private_and_scheduled', 'alarms', (
        r'(?:поставь|поставить|создай|создать|заведи|завести|установи|установить|удали|отмени|перенеси|покажи|выключи) (?:мне |мой |мои )?будильник(?:и)?' + _OPTIONAL_TAIL,
        r'разбуди(?: меня)? (?:завтра |сегодня )?(?:в|на|через) ' + _TAIL,
    )),
    ('private_and_scheduled', 'persistent_lists', (
        r'(?:добавь|внеси|запиши|убери|удали|вычеркни) ' + _TAIL + r' (?:в|из) (?:мой |моего |постоянный |общий )?спис(?:ок|ка) покупок',
        r'(?:покажи|прочитай|очисти) (?:мой |постоянный |общий )?список покупок',
    )),
    ('connected_services', 'communications', (
        r'(?:позвони|позвонить|набери) ' + _TAIL,
        r'(?:отправь|отправить|пошли) (?:сообщение|смс|sms|письмо)' + _OPTIONAL_TAIL,
    )),
    ('connected_services', 'mail', (
        r'(?:покажи|прочитай|проверь|открой) (?:мою |входящую |новую )?(?:почту|входящие письма)' + _OPTIONAL_TAIL,
    )),
    ('connected_services', 'news', (
        # Information requests retain the existing current-fact verification
        # route. Only a request to start news media is a new adapter command.
        r'включи (?:свежие |последние |сегодняшние )?новости' + _OPTIONAL_TAIL,
    )),
    ('connected_services', 'taxi', (r'(?:закажи|вызови|вызвать) (?:мне )?такси' + _OPTIONAL_TAIL,)),
    ('connected_services', 'shopping', (r'(?:закажи|заказать) (?:продукты|пиццу|еду|доставку еды)' + _OPTIONAL_TAIL,)),
    ('connected_services', 'delivery', (r'(?:проверь|узнай|покажи) статус (?:доставки|заказа|посылки)' + _OPTIONAL_TAIL,)),
    ('connected_services', 'navigation', (r'(?:проложи|построй) маршрут (?:до|в|к) ' + _TAIL,)),
    ('connected_services', 'traffic', (r'(?:проверь|покажи|какие сейчас) пробки' + _OPTIONAL_TAIL,)),
    ('connected_services', 'find_phone', (r'(?:найди|отыщи) (?:мой )?телефон',)),
)


def command_value(value):
    """Small full-command normalization; no edits to negation or quoted text."""
    if not isinstance(value, str) or len(value) > 200 or '\n' in value or '\r' in value:
        return None
    value = _normal(value)
    for _ in range(2):
        value = re.sub(r'^(?:гобот[, ]+|пожалуйста[, ]+)', '', value)
    value = re.sub(r'^(?:ты можешь|можешь(?: ли)?(?: ты)?|давай(?:[- ]ка)?)[, ]+', '', value)
    value = re.sub(r'[, ]+пожалуйста$', '', value)
    if (not value or value[0] in '\"\'«“„`' or re.search(r'\b(?:не|нет|нельзя|никогда)\b', value)
            or re.search(r'[;\n\r]|(?<!\d):|:(?!\d)', value)
            or re.search(r'\b(?:и|или|но|затем|потом)\s+(?:не\s+)?(?:включи|выключи|отмени|удали|добавь|поставь|напомни|создай|переведи|расскажи|объясни|напиши|прочитай|покажи|запусти|отправь|вызови)\b', value)
            or re.match(r'^(?:объясни|переведи(?! деньги\b)|расскажи как|как|почему|зачем|что значит|что означает|фраза|команда|цитата|пример)\b', value)):
        return None
    return value


def external_request(value):
    """Return only capability/category for a full unavailable-operation shape."""
    value = command_value(value)
    if value is None:
        return None
    matches = {
        (category, capability)
        for category, capability, patterns in _GUARDS
        if any(re.fullmatch(pattern, value) for pattern in patterns)
    }
    if len(matches) != 1:
        return None
    category, capability = matches.pop()
    return {'category': category, 'capability': capability}
