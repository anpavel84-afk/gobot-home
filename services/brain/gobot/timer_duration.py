"""Shared deterministic timer syntax for the router and the local tool."""
import re
from decimal import Decimal

WORDS={'одну':1,'один':1,'две':2,'два':2,'три':3,'четыре':4,'пять':5,
       'шесть':6,'семь':7,'восемь':8,'девять':9,'десять':10,'пятнадцать':15,
       'одна':1,'одной':1,'одну':1,'одиннадцать':11,'двенадцать':12,'тринадцать':13,'четырнадцать':14,
       'шестнадцать':16,'семнадцать':17,'восемнадцать':18,'девятнадцать':19,
       'двадцать':20,'тридцать':30,'сорок':40,'пятьдесят':50,'шестьдесят':60,'семьдесят':70,'восемьдесят':80,'девяносто':90,
       'полторы':'1.5','полтора':'1.5'}
NUMBER=r'-?\d+(?:[.,]\d+)?|'+'|'.join(WORDS)
UNIT=r'секунд(?:а|у|ы)?|сек|с|минут(?:а|у|ы)?|мин|час(?:а|ов)?|ч'
PART=re.compile(r'(?<![\w.,])('+NUMBER+r')\s*('+UNIT+r')\b\.?',re.I)

def timer_seconds(text):
    text=' '.join(text.casefold().replace('ё','е').strip().split()).rstrip('!?')
    text=re.sub(r'^(?:(?:поставь|поставить|установи|установить|запусти|запустить|включи|включить)(?: мне)? таймер|таймер|(?:засеки|засечь|засекай|отсчитай|отсчитать)(?: мне)?(?: таймер)?)(?: на)?\s*','',text)
    text=re.sub(r'^на\s+','',text)
    text=re.sub(r'[, ]+пожалуйста[.!?]*$','',text)
    if re.search(r'\b(?:не|или|либо)\b',text):return None
    if re.fullmatch(r'полчаса[.!?]*',text):return 1800
    if re.fullmatch(r'полминуты[.!?]*',text):return 30
    if re.fullmatch(r'четверть часа[.!?]*',text):return 900
    if re.fullmatch(r'час[.!?]*',text):return 3600
    if re.fullmatch(r'(?:минуту|минута)[.!?]*',text):return 60
    if re.fullmatch(r'(?:секунду|секунда)[.!?]*',text):return 1
    tens={word:value for word,value in WORDS.items() if type(value) is int and value>=20}
    ones={word:value for word,value in WORDS.items() if type(value) is int and 1<=value<=9}
    text=re.sub(r'\b('+'|'.join(tens)+r') ('+'|'.join(ones)+r')\b',lambda m:str(tens[m[1]]+ones[m[2]]),text)
    matches=list(PART.finditer(text))
    if not matches:return None
    # Do not turn an unsupported compound number into its final word/digits.
    prefix=text[:matches[0].start()]
    if re.search(r'\bминус\b',prefix):return 0
    if prefix.strip():return None
    if re.search(r'\d|\b(?:'+'|'.join(WORDS)+r')\b',prefix):return None
    from .speech_formatter import morphology
    if any(any(p.tag.POS=='NUMR' for p in morphology().parse(word)) for word in re.findall(r'[а-яё]+',prefix)):return None
    total=Decimal(0);previous_unit=86401
    for index,match in enumerate(matches):
        if len(match[1])>12:return None
        if index and not re.fullmatch(r'\s*(?:и\s+)?',text[matches[index-1].end():match.start()]):return None
        value=Decimal(WORDS[match[1]]) if match[1] in WORDS else Decimal(match[1].replace(',','.'))
        unit=3600 if match[2].startswith(('час','ч')) else 60 if match[2].startswith('мин') else 1
        if unit>=previous_unit:return None
        if value<0:return 0
        previous_unit=unit;total+=value*unit
    # A second command/alternative is not a timer label. Never silently drop it.
    if text[matches[-1].end():].strip(' ,.!?') not in {'','пожалуйста'}:return None
    return int(total) if total==total.to_integral_value() else None

def is_timer_duration_reply(text):
    text=re.sub(r'^на\s+','',text.casefold().replace('ё','е').strip()).rstrip('!?').strip()
    # A duration answer may use every supported duration grammar, but no verb or
    # unrelated sentence. The same strict parser validates the entire value.
    if not re.match(r'^(?:-?\d|(?:'+ '|'.join(WORDS)+r'|полчаса|полминуты|четверть|час|минут[ау]|секунд[ау])\b)',text):return False
    return timer_seconds(text) is not None

def duration_text(seconds):
    parts=[]
    for unit,forms in [(3600,('час','часа','часов')),(60,('минуту','минуты','минут')),(1,('секунду','секунды','секунд'))]:
        count,seconds=divmod(seconds,unit)
        if count:
            ending=2 if 11<=count%100<=14 else 0 if count%10==1 else 1 if 2<=count%10<=4 else 2
            parts.append(str(count)+' '+forms[ending])
    return ' '.join(parts)
