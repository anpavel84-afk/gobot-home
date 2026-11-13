"""Deterministic vNext interpretation. Existing Open-Meteo remains the source."""
import math
from decimal import Decimal,ROUND_HALF_UP
from .hybrid_contract import AnswerEnvelope
from .speech_formatter import SpeechFormatter,words,noun_form

def finite(value):
    try:
        if value is None or isinstance(value,bool):return None
        n=float(value);return n if math.isfinite(n) else None
    except (ValueError,TypeError):return None

def degrees(value,*,prefix='',exact=False):
    n=finite(value)
    if n is None:return 'нет данных о температуре'
    rounded=int(Decimal(str(n)).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
    # A rounded negative zero would lose the sign: retain precision near zero.
    if exact or n<0 and rounded==0:
        return SpeechFormatter().format((prefix+' ' if prefix else '')+format(n,'g')+' °C')
    case='genitive' if prefix in {'около','до','от'} else 'nominative'
    return ((prefix+' ') if prefix else '')+words(rounded,case=case)+' '+noun_form('градус',rounded,case)

def envelope(result,*,exact=False,epoch=0):
    frame=result.frame.model_dump() if result.frame else {}
    if not frame or not (result.evidence or {}).get('verified'):
        return AnswerEnvelope(speech_text=result.text,display_data={'frame':frame} if frame else {},presentation_epoch=epoch)
    meta=frame['metadata'];weather=meta.get('weather') or {};facts=meta.get('facts') or {}
    place=weather.get('place') or frame.get('subtitle','');metric=weather.get('metric','summary')
    canonical={'location':place,'kind':weather.get('kind'),'timezone':weather.get('timezone'),
        'days':weather.get('days',[]),'values':facts,'method':'forecast_model','not_sensor_measurement':True}
    if weather.get('kind')=='forecast':
        rows=weather.get('days') or []
        if not rows:return AnswerEnvelope(speech_text='Источник не вернул прогноз.',canonical_facts=canonical)
        parts=[]
        for row in rows[:2]:
            title='На '+row['date']+': '
            if metric=='wind':line='ветер до '+str(row.get('wind_kmh','нет данных'))+' км/ч.'
            elif metric in {'precipitation','umbrella'}:
                rain=finite(row.get('rain_percent'))
                line='данных о вероятности осадков нет.' if rain is None else 'вероятность осадков '+format(rain,'g')+' процентов.'
                if metric=='umbrella' and rain is not None:
                    line+=' '+('Зонт стоит взять: вероятность не ниже сорока процентов.' if rain>=40 else 'Вероятность ниже сорока процентов, но это не гарантия сухой погоды.')
            elif metric in {'humidity','uv_index'}:line=result.text.split('. ',1)[-1]
            else:
                high=finite(row.get('high'));low=finite(row.get('low'))
                line=row.get('condition','')+'. Днём '+degrees(high,prefix='до',exact=exact)+', минимум '+degrees(low,exact=exact)+'.'
            parts.append(title+line)
        if len(rows)>2:parts.append('Полный прогноз на экране. Дальний прогноз может меняться.')
        speech='По прогнозу Open-Meteo для '+place+'. '+' '.join(parts)
    elif metric=='summary' or metric=='temperature':
        value=finite(facts.get('temperature'))
        speech='По данным Open-Meteo для '+place+': '+weather.get('condition','')+', '+degrees(value,prefix='' if exact or value is None or value.is_integer() else 'около',exact=exact)+'.'
        wind=finite(facts.get('wind_kmh'))
        if wind is not None:speech+=' Ветер '+format(wind,'g')+' км/ч.'
    else:speech=result.text
    return AnswerEnvelope(canonical_facts=canonical,speech_text=SpeechFormatter().format(speech),
        display_data={'frame':frame},source='Open-Meteo · прогнозная модель',valid_until=frame.get('expires_at'),
        template_id='weather_vnext_v1',presentation_epoch=epoch)
