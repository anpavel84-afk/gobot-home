"""Conservative deterministic oral rendering; display text is never modified."""
import json
import re
from pathlib import Path
from functools import lru_cache
from num2words import num2words
import pymorphy3

@lru_cache(maxsize=1)
def morphology():
    return pymorphy3.MorphAnalyzer()

MONTHS=['января','февраля','марта','апреля','мая','июня','июля','августа','сентября','октября','ноября','декабря']
CASES={'gent':'genitive','datv':'dative','ablt':'instrumental','loct':'prepositional'}
PREPOSITIONS={'до':'genitive','от':'genitive','около':'genitive','после':'genitive','без':'genitive','более':'genitive','менее':'genitive','к':'dative','свыше':'genitive','между':'instrumental','перед':'instrumental'}
UNITS={'кг':('килограмм','masculine'),'км':('километр','masculine'),'см':('сантиметр','masculine'),'мм':('миллиметр','masculine'),'мс':('миллисекунда','feminine'),'мл':('миллилитр','masculine'),'г':('грамм','masculine'),'м':('метр','masculine'),'л':('литр','masculine'),'₽':('рубль','masculine'),'руб.':('рубль','masculine'),'$':('доллар','masculine'),'€':('евро','neuter'),'%':('процент','masculine'),'°C':('градус Цельсия','masculine')}

def words(value,case='nominative',gender='masculine',ordinal=False):
    return num2words(value,lang='ru',to='ordinal' if ordinal else 'cardinal',case=case,gender=gender)

def noun_form(noun,number,case):
    head,*tail=noun.split(' ',1);parsed=morphology().parse(head)[0]
    n=abs(int(number));last=n%10
    grammemes={'gent','plur'} if n%100 in range(11,15) or last==0 or last>=5 else {'nomn','sing'} if last==1 else {'gent','sing'}
    if case!='nominative':
        code=next((k for k,v in CASES.items() if v==case),'gent')
        grammemes={code,'sing' if last==1 and n%100!=11 else 'plur'}
    inflected=parsed.inflect(grammemes)
    return (inflected.word if inflected else head)+(' '+tail[0] if tail else '')

def normalize_name(value):
    # Only prove a duplicate; never replace an unrelated foreign name.
    value=value.lower().replace('catherine','кэтрин').replace('katherine','кэтрин').replace('zeta','зета').replace('jones','джонс')
    for key,val in {'shch':'щ','sch':'щ','ch':'ч','sh':'ш','zh':'ж','kh':'х','th':'т','ph':'ф','qu':'кв','ya':'я','yu':'ю','yo':'ё'}.items():value=value.replace(key,val)
    table=str.maketrans({'a':'а','b':'б','c':'к','d':'д','e':'е','f':'ф','g':'г','h':'х','i':'и','j':'дж','k':'к','l':'л','m':'м','n':'н','o':'о','p':'п','q':'к','r':'р','s':'с','t':'т','u':'у','v':'в','w':'в','x':'кс','y':'и','z':'з'})
    return re.sub(r'[^а-яё]','',value.translate(table)).replace('ё','е')

class SpeechFormatter:
    version=3
    def __init__(self,dictionary=None):
        self.in_code=False
        path=Path(__file__).parents[1]/'pronunciations.json'
        self.dictionary=dictionary if dictionary is not None else json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}

    def format(self,text):
        parts=text.split('```');out=[]
        for index,part in enumerate(parts):
            if index:self.in_code=not self.in_code
            if not self.in_code:out.append(part)
        text=' '.join(out)
        text=re.sub(r'\[([^\]]+)\]\(https?://[^)]+\)',r'\1',text)
        text=re.sub(r'https?://[^\s)]+','ссылка на экране',text)
        text=re.sub(r'(?m)^\s*(?:#{1,6}\s+|[-*+]\s+|\d+[.)]\s+)','',text)
        text=re.sub(r'[*_`|]','',text)
        def parenthesis(match):
            before,foreign=match[1],match[2];foreign_key=normalize_name(foreign);tokens=before.split()
            for count in range(1,len(tokens)+1):
                if normalize_name(' '.join(tokens[-count:]))==foreign_key:return before.rstrip()
            return match[0]
        text=re.sub(r'([А-ЯЁа-яё][А-ЯЁа-яё\s-]{0,90})\s*\(([A-Za-z][A-Za-z\s-]{0,80})\)',parenthesis,text)
        for source,target in sorted(self.dictionary.items(),key=lambda pair:-len(pair[0])):
            text=re.sub(r'(?<!\w)'+re.escape(source)+r'(?!\w)',lambda _:target,text)
        def date(match):
            day,month,year=map(int,match.groups())
            import datetime
            try:datetime.date(year,month,day)
            except ValueError:return match[0]
            prefix=text[max(0,match.start()-20):match.start()].lower();case='dative' if re.search(r'\bк\s*$',prefix) else 'genitive'
            return words(day,case,ordinal=True)+' '+MONTHS[month-1]+' '+words(year,'genitive',ordinal=True)+' года'
        text=re.sub(r'\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b',date,text)
        # Calendar dates use ordinal days, before the general cardinal-number pass.
        months='|'.join(MONTHS)
        def calendar_case(prefix,suffix=None):
            if suffix:return {'го':'genitive','му':'dative','е':'nominative','ым':'instrumental','ом':'prepositional'}[suffix]
            if re.search(r'\bк\s*$',prefix):return 'dative'
            if re.search(r'\b(?:перед|между)\s*$',prefix):return 'instrumental'
            if re.search(r'\b(?:о|об)\s*$',prefix):return 'prepositional'
            if re.search(r'\b(?:на|по)\s*$|\b(?:сегодня|завтра|вчера)(?:\s+(?:будет|было|уже))?\s*$',prefix):return 'nominative'
            return 'genitive'
        def calendar_day(value,case):return words(int(value),case,'neuter' if case=='nominative' else 'masculine',ordinal=True)
        def date_range(match):
            start,one,link,two,month=match.groups()
            if not (1<=int(one)<=31 and 1<=int(two)<=31):return match[0]
            first='instrumental' if start.lower()=='между' else 'genitive'
            second='nominative' if link.lower()=='по' else first
            return start+' '+calendar_day(one,first)+' '+link+' '+calendar_day(two,second)+' '+month
        text=re.sub(r'\b(с|между)\s+(\d{1,2})\s+(по|до|и)\s+(\d{1,2})\s+('+months+r')\b',date_range,text,flags=re.I)
        def named_date(match):
            day,suffix,month,year_value=match.groups()
            import datetime
            try:datetime.date(int(year_value or 2000),MONTHS.index(month.lower())+1,int(day))
            except ValueError:return match[0]
            case=calendar_case(text[max(0,match.start()-45):match.start()].lower(),suffix.lower() if suffix else None)
            result=calendar_day(day,case)+' '+month
            if year_value:result+=' '+words(int(year_value),'genitive',ordinal=True)+' года'
            return result
        text=re.sub(r'\b(\d{1,2})(?:-?(го|му|е|ым|ом))?\s+('+months+r')(?:\s+(\d{4})(?:\s+года)?)?\b',named_date,text,flags=re.I)
        def year(match):
            prep,value,noun=match.groups();case={'в':'prepositional','до':'genitive','после':'genitive','от':'genitive','с':'genitive','к':'dative'}.get(prep.lower(),'genitive')
            return prep+' '+words(int(value),case,ordinal=True)+' '+noun
        text=re.sub(r'\b(в|до|после|от|с|к)\s+(\d{4})\s+(году|года|год)\b',year,text,flags=re.I)
        def number(match):
            raw,noun=match.groups();value=raw.replace(',','.');prefix=text[max(0,match.start()-40):match.start()].lower()
            punctuation=''
            if noun.endswith('.') and noun not in UNITS and noun[:-1] in UNITS:noun=noun[:-1];punctuation='.'
            prep=re.search(r'(\w+)\s*$',prefix);case=PREPOSITIONS.get(prep[1] if prep else '', 'nominative');gender='masculine';original=noun
            if noun in UNITS:noun,gender=UNITS[noun]
            elif noun:
                parsed=next((p for p in morphology().parse(noun.rstrip('.')) if p.tag.POS=='NOUN'),None)
                if parsed:
                    gender={'femn':'feminine','neut':'neuter'}.get(parsed.tag.gender,'masculine')
                    if case=='nominative' and parsed.tag.case in {'datv','ablt','loct'}:case=CASES[parsed.tag.case]
            if len(raw)>16:return ' '.join(words(int(d)) for d in raw if d.isdigit())+(' '+original if original else '')
            if '.' in value:
                whole,fraction=value.split('.')
                denominator={1:'десятая',2:'сотая',3:'тысячная',4:'десятитысячная',5:'стотысячная',6:'миллионная'}.get(len(fraction))
                def fractional_adjective(base,number):
                    single=abs(number)%10==1 and abs(number)%100!=11
                    code=next((k for k,v in CASES.items() if v==case),'nomn')
                    tags={code,'sing','femn'} if single else {'gent' if code=='nomn' else code,'plur'}
                    parsed=morphology().parse(base)[0];inflected=parsed.inflect(tags)
                    return inflected.word if inflected else base
                spoken=words(int(whole),case,'feminine')+' '+fractional_adjective('целая',int(whole))+' '+words(int(fraction),case,'feminine')+' '+fractional_adjective(denominator,int(fraction)) if denominator else words(int(whole),case)+' запятая '+' '.join(words(int(d)) for d in fraction)
                if raw.startswith('-') and int(whole)==0:spoken='минус '+spoken
            else:spoken=words(int(value),case,gender)
            if raw.startswith('+'):spoken='плюс '+spoken
            if original in UNITS:
                form=noun_form(noun,int(value),case) if '.' not in value else (morphology().parse(noun.split()[0])[0].inflect({'gent','sing'}).word+(' '+' '.join(noun.split()[1:]) if ' ' in noun else ''))
                return spoken+' '+form+punctuation
            return spoken+(' '+original if original else '')
        text=re.sub(r'(?<![\w.])([+-]?\d+(?:[.,]\d+)?)[ \u00a0]*(°C|₽|\$|€|%|[А-ЯЁа-яё]+\.?|)(?!\w)',number,text)
        return re.sub(r'\s+',' ',text).strip()
