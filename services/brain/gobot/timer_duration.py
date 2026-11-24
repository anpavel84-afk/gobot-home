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

# Only complete, deterministic duration expressions are accepted. A model may
# normalize words or units; the server's own transcript remains authoritative.
_NUM_WORDS = {**WORDS, 'сто':100, 'двести':200, 'триста':300,
    'четыреста':400, 'пятьсот':500, 'шестьсот':600, 'семьсот':700,
    'восемьсот':800, 'девятьсот':900}
_NUMBER = r'(?:-?\d+(?:[.,]\d+)?|'+'|'.join(_NUM_WORDS)+r')'
_UNIT = r'(?:секунд(?:а|у|ы|очку|очка)?|сек|с|минут(?:а|у|ы|ку|ка)?|мин|час(?:а|ов|ик)?|ч)'
_PART = re.compile(r'(?<![\w.,])('+_NUMBER+r')\s*('+_UNIT+r')\b\.?',re.I)
_PREFIX = r'(?:(?:софия|софья|гобот|кстати|слушай|пожалуйста)[,\s]+)*'
_POLITE = r'(?:(?:можешь|можете|могла\s+бы|не\s+могла\s+бы|не\s+мог\s+бы|давай)[,\s]+)?'
_VERBS = r'(?:поставь(?:те)?|поставить|установи(?:те)?|установить|запусти(?:те)?|запустить|включи(?:те)?|включить|сделай(?:те)?|сделать)'
_FILL = r'(?:[,\s]+(?:мне|нам|пожалуйста))*'
_CMD = r'(?:(?:'+_VERBS+_FILL+r'[,\s]+)?таймер|(?:засеки(?:те)?|засечь|засекай|отсчитай(?:те)?|отсчитать)'+_FILL+r'(?:[,\s]+таймер)?)'
_REQUEST = re.compile(r'^'+_PREFIX+_POLITE+_CMD+r'(?:[,\s]+(?:мне|нам|пожалуйста))*[,\s]*(?:на\s+)?(.+)$')
_REVERSE_REQUEST = re.compile(r'^'+_PREFIX+r'(.+?)[,\s]+'+_POLITE+_VERBS+_FILL+r'[,\s]+таймер(?:[,\s]+пожалуйста)?$')


def _clean(text):
    if not isinstance(text,str) or len(text)>4096:
        return ''
    return ' '.join(text.casefold().replace('ё','е').replace('\u00a0',' ').strip().split()).rstrip('!?').strip()


def _words_to_digits(text):
    hundreds={w:v for w,v in _NUM_WORDS.items() if type(v) is int and v>=100}
    tens={w:v for w,v in WORDS.items() if type(v) is int and 20<=v<=90}
    ones={w:v for w,v in WORDS.items() if type(v) is int and 1<=v<=9}
    small={w:v for w,v in WORDS.items() if type(v) is int and 1<=v<=19}
    # Consume a whole well-formed compound, never just its trailing number.
    h='|'.join(hundreds); t='|'.join(tens); o='|'.join(ones); s='|'.join(small)
    pattern=r'\b('+h+r')(?: (?:(?:('+t+r')(?: ('+o+r'))?)|('+s+r')))?\b'
    text=re.sub(pattern,lambda m:str(hundreds[m[1]]+(tens[m[2]] if m[2] else 0)+(ones[m[3]] if m[3] else 0)+(small[m[4]] if m[4] else 0)),text)
    return re.sub(r'\b('+t+r') ('+o+r')\b',lambda m:str(tens[m[1]]+ones[m[2]]),text)


def _bare_seconds(text, *, colon_allowed=False):
    text=_clean(text)
    text=re.sub(r'^на\s+','',text)
    text=re.sub(r'[, ]+пожалуйста[.!?]*$','',text).strip()
    if not text or any(c in text for c in '«»“”"') or re.search(r'\b(?:не|или|либо)\b',text):
        return None
    # Two fields mean minutes:seconds only for an explicitly requested timer
    # (or its pending duration reply); three fields are hours:minutes:seconds.
    # Clock-time requests ("в 12:30", "до 12:30") are never parsed as durations.
    clock=re.fullmatch(r'(\d{1,4}):(\d{2})(?::(\d{2}))?\.?',text)
    if clock:
        if not colon_allowed:return None
        a,b=int(clock[1]),int(clock[2])
        if b>=60 or clock[3] is not None and int(clock[3])>=60:return None
        return a*3600+b*60+int(clock[3]) if clock[3] is not None else a*60+b
    negative=text.startswith('минус ')
    if negative:text=text[6:].strip()
    text=_words_to_digits(text)
    # Full-unit colloquialisms and half units. Standalone implicit units are
    # allowed; a bare number with no unit is still genuinely ambiguous.
    text=re.sub(r'\b(?:пол\s*часа|половин[ауы]\s+часа)\b','0.5 часа',text)
    text=re.sub(r'\b(?:пол\s*минуты|половин[ауы]\s+минуты)\b','0.5 минуты',text)
    text=re.sub(r'\bчетверть\s+часа\b','0.25 часа',text)
    text=re.sub(r'\bчас\s+с\s+половиной\b','1.5 часа',text)
    text=re.sub(r'\bминут[ау]\s+с\s+половиной\b','1.5 минуты',text)
    def half(m):
        v=_NUM_WORDS.get(m[1],m[1])
        return str(Decimal(str(v).replace(',','.'))+Decimal('0.5'))+' '+m[2]
    # Only an integral count followed by "с половиной", not a double fraction.
    integer=r'(?:\d{1,9}|'+'|'.join(w for w,v in _NUM_WORDS.items() if type(v) is int)+r')'
    text=re.sub(r'\b('+integer+r')\s+с\s+половиной\s+('+_UNIT+r')\b',half,text)
    reverse=re.fullmatch(r'('+_UNIT+r')\s+(?:на\s+)?('+_NUMBER+r')\.?',text)
    if reverse:text=reverse[2]+' '+reverse[1]
    # "час и 20 минут", "минуту тридцать секунд".
    text=re.sub(r'^(час|минут[ау]|минутк[ау]|секунд[ау]|секундочк[ау])(?=\b)(?=\s*(?:[.,]?$|[, ]+(?:и\s+)?'+_NUMBER+r'\s*'+_UNIT+r'\b))',r'1 \1',text)
    matches=list(_PART.finditer(text))
    if not matches or text[:matches[0].start()].strip():return None
    total=Decimal(0); previous_unit=86401
    for index,match in enumerate(matches):
        if len(match[1])>12:return None
        if index and not re.fullmatch(r'(?:\s|,)*(?:и\s+)?',text[matches[index-1].end():match.start()]):return None
        value=Decimal(str(_NUM_WORDS.get(match[1],match[1])).replace(',','.'))
        unit=3600 if match[2].startswith(('час','ч')) else 60 if match[2].startswith('мин') else 1
        if unit>=previous_unit:return None
        if value<0:return 0
        previous_unit=unit; total+=value*unit
    if text[matches[-1].end():].strip(' ,.!?') not in {'','пожалуйста'}:return None
    if negative:return 0
    return int(total) if total==total.to_integral_value() else None


def timer_seconds(text):
    text=_clean(text)
    # Try complete duration first, then a bounded direct request. Never extract
    # a number from arbitrary prose or silently skip a second command.
    value=_bare_seconds(text,colon_allowed=True)
    if value is not None:return value
    match=_REQUEST.fullmatch(text) or _REVERSE_REQUEST.fullmatch(text)
    return _bare_seconds(match[1],colon_allowed=True) if match else None


def is_timer_duration_reply(text):
    # No command stripping here: a bare duration requires an existing pending
    # timer request in the native executor.
    return _bare_seconds(text,colon_allowed=True) is not None


def source_timer_seconds(text,source):
    """Resolve an equivalent complete duration from an actual user utterance.

    Selection is not authorization. The native coordinator separately owns the
    current user decision. This check prevents a model from inventing seconds or
    extracting five minutes from twenty-five, or only half a compound duration.
    """
    if (not isinstance(text,str) or not isinstance(source,str) or not 1<=len(source)<=120 or
            source!=source.strip()):
        raise ValueError('timer_duration_source_mismatch')
    whole=timer_seconds(text)
    if whole is not None:
        # Equivalence is safe only when the complete original request/reply
        # contains one unambiguous duration. Conflicting values still fail.
        if timer_seconds(source)==whole:return whole
        raise ValueError('timer_duration_source_mismatch')
    if text.count(source)!=1:
        raise ValueError('timer_duration_source_mismatch')
    start=text.index(source);end=start+len(source)
    if (start and text[start-1].isalnum()) or (end<len(text) and text[end].isalnum()):
        raise ValueError('timer_duration_source_mismatch')
    for quote in re.finditer(r'«[^»]*»|“[^”]*”|"[^"]*"',text):
        if quote.start()<=start and end<=quote.end():
            raise ValueError('timer_duration_source_mismatch')
    before=text[:start].casefold().replace('ё','е').rstrip(' ,.;:!?')
    after=text[end:].casefold().replace('ё','е').lstrip(' ,.;:!?')
    # A connector belongs to a neighboring duration, not permission to omit it.
    if re.search(r'\b(?:или|либо)\s*$',before) or re.match(r'(?:или|либо)\b',after):
        raise ValueError('timer_duration_source_mismatch')
    before=re.sub(r'\bи\s*$','',before).rstrip(' ,.;:!?')
    after=re.sub(r'^и\s+','',after)
    previous=re.search(r'([а-яa-z0-9.,-]+)\s*$',before)
    following=re.match(r'([а-яa-z0-9.,-]+)',after)
    def numeric_or_unit(word):
        word=word.strip('.,')
        if word in WORDS or word in {'минус','полчаса','полминуты','четверть'} or re.fullmatch(r'-?\d+(?:[.,]\d+)?',word):return True
        if re.fullmatch(r'(?:'+UNIT+r')\.?',word):return True
        from .speech_formatter import morphology
        return any(p.tag.POS=='NUMR' for p in morphology().parse(word))
    if previous and numeric_or_unit(previous[1]) or following and numeric_or_unit(following[1]):
        raise ValueError('timer_duration_source_mismatch')
    return timer_seconds(source)

def duration_text(seconds):
    parts=[]
    for unit,forms in [(3600,('час','часа','часов')),(60,('минуту','минуты','минут')),(1,('секунду','секунды','секунд'))]:
        count,seconds=divmod(seconds,unit)
        if count:
            ending=2 if 11<=count%100<=14 else 0 if count%10==1 else 1 if 2<=count%10<=4 else 2
            parts.append(str(count)+' '+forms[ending])
    return ' '.join(parts)
