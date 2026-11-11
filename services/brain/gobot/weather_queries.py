"""Whole weather requests; no LLM, source selection or settings mutations."""
import re

DAY_WORDS={'один':1,'два':2,'три':3,'четыре':4,'пять':5,'шесть':6,'семь':7,'десять':10,'четырнадцать':14,'пятнадцать':15,'шестнадцать':16}
HOME_REFERENCE = (r'(?:там\s+же(?:\s*,?\s*где(?:\s+и)?\s+(?:сегодня|сейчас|мы|я нахожусь))?'
                  r'|в\s+(?:том\s+же\s+месте|моем\s+городе|нашем\s+городе|моем\s+местоположении|нашем\s+районе)'
                  r'|для\s+(?:того\s+же\s+города|моего\s+города|нашего\s+города|меня|нас)'
                  r'|там\s*,?\s*где\s+я\s+нахожусь|здесь|у\s+нас|дома)')


def weather_words(value):
    """Conversational wrappers for read-only weather, never global action parsing."""
    value=' '.join(value.casefold().replace('ё','е').strip().rstrip('.!?').split())
    for _ in range(5):
        value=re.sub(r'^(?:ну|хорошо|ладно|тогда|ага|отлично|окей|а|и|пожалуйста)[,\s]+','',value).strip()
    return value


def weather_followup(value,context):
    if not (context or {}).get('weather_followup'):return None
    value=weather_words(value)
    value=re.sub(r'^(?:нет[,\s]+|я (?:имел в виду|сказал)\s+)','',value)
    value=re.sub(r'^не (?:сегодня|завтра|послезавтра)[,\s]+а\s+','',value)
    without_home=' '.join(re.sub(r'\b'+HOME_REFERENCE+r'\b','',value).strip(' ,').split())
    last=(context or {}).get('weather_last_request') or {'operation':'weather_current'}
    if not isinstance(last,dict):return None
    last={k:last[k] for k in ('operation','offset','days','weekday') if k in last}
    if last.get('operation') not in {'weather_current','weather_forecast'}:return None
    if not without_home and value:return last
    period=r'(?:(?:на )?(?:завтра|послезавтра|сегодня)|сейчас|на (?:неделю|две недели|выходные|выходных|\d{1,2} дней)|в (?:понедельник|вторник|среду|четверг|пятницу|субботу|воскресенье))'
    if re.fullmatch(period,without_home):return weather_query('погода '+without_home)
    # A property followup inherits the selected date/range, then refreshes the
    # source. A previous model answer is not itself a weather source.
    if re.fullmatch(r'(?:(?:какой|какая|какие|будет ли|нужен ли) )?(?:ветер|дождь|осадки|температура|снег|зонт)(?: (?:будет|будут|ожидается|ожидаются))?',without_home):return last
    return None


def weather_query(value):
    value=weather_words(value)
    if re.search(r'\b(?:не проверяй|не показывай|не узнавай|как работает|что такое|объясни|цитата)\b',value):return None
    if re.search(r'температур.*(?:тела|ребен|больн|кипен|плавлен|духов|процессор|двигател)|солнечн\w* ветер',value):return None
    if re.match(r'^как ',value) and not re.match(r'^как (?:там |сейчас |завтра )?погод',value):return None
    if not re.search(r'погод|прогноз',value) and not re.search(r'завтра|послезавтра|сегодня|сейчас|через|недел|выходн|будет|будут|ожида|нужен|на улице|за окном',value):return None
    topic=r'(?:погод\w*|прогноз\w*|температур\w*|дожд\w*|осадк\w*|ветер|снег|гроз\w*|зонт)'
    if not re.search(r'\b'+topic+r'\b',value):return None
    if not re.match(r'^(?:(?:какая|какой|какие|как|покажи|показать|проверь|проверить|узнай|узнать|посмотри|посмотреть|скажи|сказать|подскажи|подсказать|расскажи|что|будет|будут|нужен|нужны|ожидается|ожидаются|сейчас|завтра|послезавтра|сегодня)\b|'+topic+r'\b)',value):return None
    if re.search(r'вчера|историческ|прошл\w*',value):return {'operation':'weather_unsupported','reason':'past'}
    if 'weather.com' in value:return {'operation':'weather_provider_unavailable'}
    if re.search(r'почасов|вечером|утром|ночью|в \d{1,2}(?::\d{2})?',value):return {'operation':'weather_unsupported','reason':'hourly'}
    if re.search(r'месяц|сезон|лето|зиму|полгода|\bгод\b',value):return {'operation':'weather_unsupported','reason':'horizon'}
    days=1;offset=2 if 'послезавтра' in value else 1 if 'завтра' in value else 0
    weekday=None
    for i,name in enumerate(['понедельник','вторник','сред','четверг','пятниц','суббот','воскресень']):
        if re.search(r'\b'+name+r'\w*',value):weekday=i;break
    if 'выходн' in value:weekday=5;days=2
    elif 'две недели' in value:days=14
    elif 'недел' in value:days=7
    match=re.search(r'\bна (\d{1,3}|'+'|'.join(DAY_WORDS)+r') (?:день|дня|дней|сутки|суток)\b',value)
    if match:days=int(match[1]) if match[1].isdigit() else DAY_WORDS[match[1]]
    after=re.search(r'\bчерез (\d{1,3}|'+'|'.join(DAY_WORDS)+r') (?:день|дня|дней|сутки|суток)\b',value)
    if after:offset=int(after[1]) if after[1].isdigit() else DAY_WORDS[after[1]];days=1
    elif 'через две недели' in value:offset=14;days=1
    elif 'через неделю' in value:offset=7;days=1
    elif 'через' in value:return {'operation':'weather_unsupported','reason':'ambiguous_period'}
    if not match and re.search(r'\bна \d',value):return {'operation':'weather_unsupported','reason':'ambiguous_date'}
    if not 1<=days<=16 or days+offset>16:return {'operation':'weather_unsupported','reason':'horizon'}
    # Locations must be resolved/confirmed separately, never silently change default.
    stripped=re.sub(r'\b'+HOME_REFERENCE+r'\b','',value)
    stripped=re.sub(r'\bв (?:понедельник|вторник|среду|четверг|пятницу|субботу|воскресенье|выходные)\b','',stripped)
    if re.search(r'\b(?:в|для)\s+\S',stripped):return {'operation':'weather_other_place'}
    forecast=bool(match or after or offset or days>1 or weekday is not None or re.search(r'прогноз|сегодня|будет|будут|дожд|осадк|зонт|снег|гроз|вечер|утр|ночь',value) and 'сейчас' not in value)
    return {'operation':'weather_forecast','offset':offset,'days':days,'weekday':weekday} if forecast else {'operation':'weather_current'}
