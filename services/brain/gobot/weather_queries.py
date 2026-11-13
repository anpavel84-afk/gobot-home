"""Bounded read-only weather grammar; never authorizes device settings."""
import re

DAY_WORDS={'один':1,'два':2,'три':3,'четыре':4,'пять':5,'шесть':6,'семь':7,'десять':10,'четырнадцать':14,'пятнадцать':15,'шестнадцать':16}
HOME_REFERENCE = (r'(?:там\s+же(?:\s*,?\s*где(?:\s+и)?\s+(?:сегодня|сейчас|мы|я нахожусь))?'
                  r'|в\s+(?:том\s+же\s+месте|моем\s+городе|нашем\s+городе|моем\s+местоположении|нашем\s+районе)'
                  r'|для\s+(?:того\s+же\s+города|моего\s+города|нашего\s+города|меня|нас)'
                  r'|там\s*,?\s*где\s+я\s+нахожусь|здесь|у\s+нас|дома)')
HOME_EXPLICIT=r'(?:дома|здесь|у\s+нас|в\s+(?:моем|нашем)\s+(?:городе|районе|местоположении)|для\s+(?:меня|нас|моего города|нашего города))'
METRICS={'summary','temperature','wind','precipitation','umbrella','humidity','uv_index'}
REQUEST_FIELDS=('operation','offset','days','weekday','metric','place_query','place_ref','place_label','timezone','start_date','end_date','calendar_period','temperature_unit','wind_unit')


def weather_request_context(slots):
    """Compact unprivileged context; coordinates and arbitrary tool fields never leave Brain."""
    if not isinstance(slots,dict):return {}
    result={}
    for key in REQUEST_FIELDS:
        if key not in slots:continue
        value=slots.get(key)
        if key in {'offset','days','weekday'}:
            if value is None and key=='weekday':result[key]=None
            elif type(value) is int and 0<=value<=16:result[key]=value
        elif isinstance(value,str) and 0<len(value)<=160 and '\n' not in value and '\r' not in value:
            result[key]=value
    if result.get('operation') not in {'weather_current','weather_forecast'}:return {}
    if result.get('metric') not in METRICS:result.pop('metric',None)
    return result


def weather_words(value):
    value=' '.join(value.casefold().replace('ё','е').strip().rstrip('.!?').split())
    for _ in range(5):
        value=re.sub(r'^(?:ну|хорошо|ладно|тогда|ага|отлично|окей|а|и|пожалуйста)[,\s]+','',value).strip()
    return value


def _metric(value):
    # A combined question needs the common source summary, not whichever word occurs first.
    groups=[r'\b(?:ветер|ветра|ветру|ветром|порыв\w*)\b',r'\b(?:дожд\w*|осадк\w*|снег\w*)\b',r'температур|градус',r'влажност',r'уф[ -]?индекс|ультрафиолет']
    if sum(bool(re.search(pattern,value)) for pattern in groups)>1:return None
    if re.search(r'\b(?:зонт|зонтик)\w*\b',value):return 'umbrella'
    if re.search(r'\b(?:ветер|ветра|ветру|ветром|порыв\w*)\b',value):return 'wind'
    if re.search(r'\b(?:дожд\w*|осадк\w*|снег\w*)\b',value):return 'precipitation'
    if re.search(r'температур|градус',value):return 'temperature'
    if re.search(r'влажност',value):return 'humidity'
    if re.search(r'уф[ -]?индекс|ультрафиолет',value):return 'uv_index'
    return None


def _rejected(value):
    return bool(re.search(r'\b(?:не надо|не нужно|не нужна|не нужен|не нужны|не интересует|не проверяй|не показывай|не узнавай|как работает|что такое|объясни|цитата|переведи|перевод|он сказал|обычно|климат)\b',value)
        or re.search(r'[«»"“”]',value)
        or re.search(r'температур.*(?:тела|ребен|больн|кипен|плавлен|духов|процессор|двигател)|солнечн\w* ветер',value))


def _temporal(value):
    return bool(re.search(r'завтра|послезавтра|сегодня|сейчас|через|недел|выходн|понедельник|вторник|сред[уы]|четверг|пятниц|суббот|воскресень',value))


def weather_followup(value,context):
    if not (context or {}).get('weather_followup'):return None
    value=weather_words(value)
    value=re.sub(r'^(?:нет[,\s]+|я (?:имел в виду|сказал)\s+)','',value)
    value=re.sub(r'^не (?:сегодня|завтра|послезавтра)[,\s]+а\s+','',value)
    if _rejected(value):return None
    last=weather_request_context((context or {}).get('weather_last_request') or {'operation':'weather_current'})
    if not last:return None
    without_home=' '.join(re.sub(r'\b'+HOME_REFERENCE+r'\b|\bтам\b','',value).strip(' ,').split())
    home=bool(re.search(r'\b'+HOME_EXPLICIT+r'\b',value))
    period=r'(?:(?:на )?(?:завтра|послезавтра|сегодня)|сейчас|на (?:следующей неделе|следующую неделю|неделю|две недели|(?:(?:эти|следующие|ближайшие) )?выходные|(?:(?:этих|следующих|ближайших) )?выходных|\d{1,2} дней)|в (?:понедельник|вторник|среду|четверг|пятницу|субботу|воскресенье))'
    prop=r'(?:(?:какой|какая|какие|будет ли|нужен ли|сколько) )?(?:ветер|порывы|дождь|осадки|температура|градусов|снег|зонт|влажность|уф[ -]?индекс)(?: (?:будет|будут|ожидается|ожидаются|и порывы|в метрах в секунду))?'
    is_period=bool(re.fullmatch(period,without_home))
    is_property=bool(re.fullmatch(prop,without_home))
    is_place=bool(re.fullmatch(r'(?:в|во|для) [^\W\d_](?:[^\W\d_]|[ ,.-]){1,99}',without_home)) and not re.fullmatch(period,without_home)
    if not without_home and value:result=dict(last)
    elif is_period:
        parsed=weather_query('погода '+without_home)
        if not parsed:return None
        if parsed['operation'] not in {'weather_current','weather_forecast'}:return parsed
        result={k:v for k,v in last.items() if k not in {'operation','offset','days','weekday','start_date','end_date','calendar_period'}}
        result.update(parsed)
    elif is_property:
        result=dict(last);result['metric']=_metric(without_home)
        if 'метрах в секунду' in without_home:result['wind_unit']='m_s'
    elif is_place:
        parsed=weather_query('погода '+without_home)
        if not parsed or not parsed.get('place_query'):return None
        result=dict(last)
        for key in ('place_query','place_ref','place_label','timezone'):result.pop(key,None)
        result['place_query']=parsed['place_query']
        if _temporal(without_home):
            for key in ('offset','days','weekday','start_date','end_date','calendar_period'):result.pop(key,None)
            result.update({k:v for k,v in parsed.items() if k not in {'place_query','metric'}})
    else:return None
    if home:
        for key in ('place_query','place_ref','place_label','timezone'):result.pop(key,None)
    return result


def _place(value):
    stripped=re.sub(r'\b'+HOME_REFERENCE+r'\b|\bтам\b','',value)
    stripped=re.sub(r'\bв (?:понедельник|вторник|среду|четверг|пятницу|субботу|воскресенье|выходные)\b','',stripped)
    stripped=re.sub(r'\bв метрах в секунду\b|\bпо (?:цельсию|фаренгейту)\b','',stripped)
    match=re.search(r'\b(?:в|во|для)\s+([^\W\d_](?:[^\W\d_]|[ ,.-]){1,99})',stripped)
    if not match:return None
    place=re.split(r'\s+(?:(?:на|в)\s+)?(?:завтра|послезавтра|сегодня|сейчас|погод\w*|прогноз\w*|недел\w*|две недели|следующ\w*|выходн\w*|через)\b',match[1],maxsplit=1)[0].strip(' ,.-')
    place=re.sub(r'\s+(?:на|через)$','',place)
    if not place or re.search(r'\b(?:и|или|либо)\b',place):return None
    return place


def weather_query(value):
    value=weather_words(value)
    if _rejected(value):return None
    value=re.sub(r'\b(?:сегодня|завтра|послезавтра)[,\s]+нет[,\s]+(?:на )?(сегодня|завтра|послезавтра)\b',r'\1',value)
    if re.match(r'^как ',value) and not re.match(r'^как (?:там |сейчас |завтра )?погод',value):return None
    topic=r'(?:погод\w*|прогноз\w*|температур\w*|дожд\w*|осадк\w*|ветер|снег|гроз\w*|зонт|влажност\w*|уф[ -]?индекс|градусов)'
    if not re.search(r'\b'+topic+r'\b',value):return None
    if not re.search(r'погод|прогноз',value) and not re.search(r'завтра|послезавтра|сегодня|сейчас|через|недел|выходн|будет|будут|ожида|нужен|на улице|за окном',value):return None
    if not re.match(r'^(?:(?:какая|какой|какие|как|сколько|покажи|показать|проверь|проверить|узнай|узнать|посмотри|посмотреть|скажи|сказать|подскажи|подсказать|расскажи|что|будет|будут|нужен|нужны|ожидается|ожидаются|сейчас|завтра|послезавтра|сегодня|в|во|сравни)\b|'+topic+r'\b)',value):return None
    if re.search(r'\b(?:на|за|через)\s*$',value):return {'operation':'weather_unsupported','reason':'ambiguous_period'}
    if re.search(r'вчера|историческ|прошл\w*',value):return {'operation':'weather_unsupported','reason':'past'}
    if 'weather.com' in value:return {'operation':'weather_provider_unavailable'}
    if re.search(r'почасов|вечером|утром|ночью|во сколько|в \d{1,2}(?::\d{2})?',value):return {'operation':'weather_unsupported','reason':'hourly'}
    if re.search(r'месяц|сезон|лето|зиму|полгода|\bгод\b',value):return {'operation':'weather_unsupported','reason':'horizon'}
    if re.search(r'\bв (?:январе|феврале|марте|апреле|мае|июне|июле|августе|сентябре|октябре|ноябре|декабре)\b',value):
        return {'operation':'weather_unsupported','reason':'horizon'}
    if re.search(r'\b(?:сравни|сравнить)\b',value):return {'operation':'weather_unsupported','reason':'comparison'}
    if re.search(r'\b(?:в|во|для)\s+[^?]+\s+(?:и|или|либо)\s+(?:в\s+)?[а-яa-z]',value) and not re.search(r'\bветер и порывы\b',value):return {'operation':'weather_unsupported','reason':'multiple_places'}
    month=r'(?:январ\w*|феврал\w*|март\w*|апрел\w*|мая|май|июн\w*|июл\w*|август\w*|сентябр\w*|октябр\w*|ноябр\w*|декабр\w*)'
    if re.search(r'\b(?:\d{1,2}|[а-я]+(?:ого|ое))\s+'+month+r'\b|\b\d{4}-\d{2}-\d{2}\b',value):return {'operation':'weather_unsupported','reason':'ambiguous_date'}
    days=1;offset=2 if 'послезавтра' in value else 1 if 'завтра' in value else 0
    weekday=None;calendar_period=None
    for i,name in enumerate(['понедельник','вторник','сред','четверг','пятниц','суббот','воскресень']):
        if re.search(r'\b'+name+r'\w*',value):weekday=i;break
    if 'выходн' in value:
        weekday=5;days=2
        if 'следующ' in value:calendar_period='next_weekend'
    elif 'две недели' in value:days=14
    elif 'недел' in value:
        days=7
        if 'следующ' in value:calendar_period='next_week'
    match=re.search(r'\bна (\d{1,3}|'+'|'.join(DAY_WORDS)+r') (?:день|дня|дней|сутки|суток)\b',value)
    if match:days=int(match[1]) if match[1].isdigit() else DAY_WORDS[match[1]]
    after=re.search(r'\bчерез (\d{1,3}|'+'|'.join(DAY_WORDS)+r') (?:день|дня|дней|сутки|суток)\b',value)
    if after:offset=int(after[1]) if after[1].isdigit() else DAY_WORDS[after[1]];days=1
    elif 'через две недели' in value:offset=14;days=1
    elif 'через неделю' in value:offset=7;days=1
    elif 'через' in value:return {'operation':'weather_unsupported','reason':'ambiguous_period'}
    if not match and re.search(r'\bна \d',value):return {'operation':'weather_unsupported','reason':'ambiguous_date'}
    if not 1<=days<=16 or days+offset>16:return {'operation':'weather_unsupported','reason':'horizon'}
    forecast=bool(match or after or offset or days>1 or weekday is not None or re.search(r'прогноз|сегодня|будет|будут|дожд|осадк|зонт|снег|гроз|вечер|утр|ночь',value) and 'сейчас' not in value)
    result={'operation':'weather_forecast','offset':offset,'days':days,'weekday':weekday} if forecast else {'operation':'weather_current'}
    if calendar_period:result['calendar_period']=calendar_period
    place=_place(value)
    if place:result['place_query']=place
    metric=_metric(value)
    if metric:result['metric']=metric
    if 'фаренгейт' in value:result['temperature_unit']='fahrenheit'
    if 'метрах в секунду' in value:result['wind_unit']='m_s'
    return result
