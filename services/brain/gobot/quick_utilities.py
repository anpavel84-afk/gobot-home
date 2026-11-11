"""Small validated local utilities; no external services, files or model calls."""
import re,calendar,secrets
from decimal import Decimal
from datetime import date

UNITS={
 'мм':('length','0.001'),'миллиметров':('length','0.001'),'см':('length','0.01'),'сантиметров':('length','0.01'),'м':('length','1'),'метров':('length','1'),'км':('length','1000'),'километров':('length','1000'),
 'дюймов':('length','0.0254'),'футов':('length','0.3048'),'миль':('length','1609.344'),
 'мг':('mass','0.001'),'г':('mass','1'),'граммов':('mass','1'),'кг':('mass','1000'),'килограммов':('mass','1000'),'тонн':('mass','1000000'),'фунтов':('mass','453.59237'),'унций':('mass','28.349523125'),
 'мл':('volume','0.001'),'л':('volume','1'),'литров':('volume','1'),'м3':('volume','1000'),
 'секунд':('time','1'),'минут':('time','60'),'часов':('time','3600'),'дней':('time','86400'),
 'байт':('data','1'),'килобайт':('data','1000'),'мегабайт':('data','1000000'),'гигабайт':('data','1000000000'),
 'м2':('area','1'),'км2':('area','1000000'),'гектаров':('area','10000'),
}
NUM=r'-?\d{1,12}(?:[.,]\d{1,6})?'
def intent(value):
    match=re.fullmatch(r'(?:переведи|сколько будет) ('+NUM+r') ([\w]+) в ([\w]+)',value)
    if match and match[2] in UNITS and match[3] in UNITS:return {'operation':'convert','value':match[1],'source':match[2],'target':match[3]}
    match=re.fullmatch(r'(?:сколько будет|посчитай|вычисли) ('+NUM+r') (?:процентов|процента|%) от ('+NUM+r')',value)
    if match:return {'operation':'percent','value':match[1],'base':match[2]}
    match=re.fullmatch(r'переведи ('+NUM+r') градусов (цельсия|фаренгейта) в (цельсий|фаренгейт)',value)
    if match:return {'operation':'temperature','value':match[1],'source':match[2],'target':match[3]}
    match=re.fullmatch(r'(?:сколько дней между|разница в днях между) (\d{4}-\d{2}-\d{2}) и (\d{4}-\d{2}-\d{2})',value)
    if match:return {'operation':'date_diff','first':match[1],'last':match[2]}
    match=re.fullmatch(r'какой день недели (\d{4}-\d{2}-\d{2})',value)
    if match:return {'operation':'weekday','date':match[1]}
    match=re.fullmatch(r'(\d{4}) год високосный',value)
    if match:return {'operation':'leap','year':int(match[1])}
    match=re.fullmatch(r'сколько дней в (\d{1,2}) месяце (\d{4}) года',value)
    if match:return {'operation':'month_days','month':int(match[1]),'year':int(match[2])}
    match=re.fullmatch(r'(посчитай слова|посчитай символы|сделай заглавными|сделай строчными|переверни текст): (.{1,150})',value)
    if match:return {'operation':'text','action':match[1],'text':match[2]}
    if value in {'подбрось монетку','брось монетку'}:return {'operation':'coin'}
    if value in {'брось кубик','брось игральный кубик'}:return {'operation':'dice','sides':6}
    match=re.fullmatch(r'брось кубик с (\d{1,3}) гранями',value)
    if match and 2<=int(match[1])<=100:return {'operation':'dice','sides':int(match[1])}
    match=re.fullmatch(r'выбери случайное число от (\d{1,6}) до (\d{1,6})',value)
    if match and int(match[1])<=int(match[2]):return {'operation':'random','low':int(match[1]),'high':int(match[2])}
    return None

def execute(slots):
    op=slots['operation']
    number=lambda v:Decimal(str(v).replace(',','.'))
    fmt=lambda v:format(v.normalize(),'f').replace('.',',') if isinstance(v,Decimal) else str(v)
    try:
        if op=='convert':
            kind,factor=UNITS[slots['source']];other,divisor=UNITS[slots['target']]
            if kind!=other:return 'Это разные виды величин; такой перевод единиц не выполнен.'
            answer=number(slots['value'])*number(factor)/number(divisor)
            return slots['value']+' '+slots['source']+' = '+fmt(round(answer,8))+' '+slots['target']+'.'
        if op=='percent':return fmt(number(slots['value'])*number(slots['base'])/100)+'.'
        if op=='temperature':
            value=number(slots['value'])
            if slots['source'].startswith('ц') and slots['target'].startswith('ф'):value=value*9/5+32
            elif slots['source'].startswith('ф') and slots['target'].startswith('ц'):value=(value-32)*5/9
            return fmt(round(value,4))+' градусов '+slots['target']+'.'
        if op=='date_diff':return str(abs((date.fromisoformat(slots['last'])-date.fromisoformat(slots['first'])).days))+' дней.'
        if op=='weekday':return ['понедельник','вторник','среда','четверг','пятница','суббота','воскресенье'][date.fromisoformat(slots['date']).weekday()]+'.'
        if op=='leap':return 'Високосный год.' if calendar.isleap(slots['year']) else 'Невисокосный год.'
        if op=='month_days':return str(calendar.monthrange(slots['year'],slots['month'])[1])+' дней.'
        if op=='text':
            text=slots['text'];action=slots['action']
            return str(len(re.findall(r'\b\w+\b',text)))+' слов.' if action=='посчитай слова' else str(len(text))+' символов.' if action=='посчитай символы' else text.upper() if action=='сделай заглавными' else text.lower() if action=='сделай строчными' else text[::-1]
        if op=='coin':return secrets.choice(['Орёл.','Решка.'])
        if op=='dice':return 'Выпало '+str(secrets.randbelow(slots['sides'])+1)+'.'
        if op=='random':return str(slots['low']+secrets.randbelow(slots['high']-slots['low']+1))+'.'
    except (ValueError,KeyError,ArithmeticError):return 'Проверьте дату, число или совместимость единиц. Расчёт не подтверждён.'
    return 'Эта операция не поддерживается.'
