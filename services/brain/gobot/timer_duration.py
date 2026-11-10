"""Shared deterministic timer syntax for the router and the local tool."""
import re
from decimal import Decimal

WORDS={'одну':1,'один':1,'две':2,'два':2,'три':3,'четыре':4,'пять':5,
       'шесть':6,'семь':7,'восемь':8,'девять':9,'десять':10,'пятнадцать':15,
       'двадцать':20,'тридцать':30}
NUMBER=r'-?\d+(?:[.,]\d+)?|'+'|'.join(WORDS)
UNIT=r'секунд(?:а|у|ы)?|сек|с|минут(?:а|у|ы)?|мин|час(?:а|ов)?|ч'
PART=re.compile(r'(?<![\w.,])('+NUMBER+r')\s*('+UNIT+r')\b\.?',re.I)

def timer_seconds(text):
    text=text.casefold().strip()
    matches=list(PART.finditer(text))
    if re.search(r'\bполчаса\b',text):return 1800 if not matches else None
    if not matches:return None
    # Do not turn an unsupported compound number into its final word/digits.
    prefix=text[:matches[0].start()]
    if re.search(r'\bминус\b',prefix):return 0
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
    text=re.sub(r'^на\s+','',text.strip(),flags=re.I).rstrip('!?').strip()
    if re.fullmatch(r'полчаса\.?',text,re.I):return True
    matches=list(PART.finditer(text))
    if not matches or matches[0].start()!=0 or matches[-1].end()!=len(text):return False
    return timer_seconds(text) is not None

def duration_text(seconds):
    parts=[]
    for unit,forms in [(3600,('час','часа','часов')),(60,('минуту','минуты','минут')),(1,('секунду','секунды','секунд'))]:
        count,seconds=divmod(seconds,unit)
        if count:
            ending=2 if 11<=count%100<=14 else 0 if count%10==1 else 1 if 2<=count%10<=4 else 2
            parts.append(str(count)+' '+forms[ending])
    return ' '.join(parts)
