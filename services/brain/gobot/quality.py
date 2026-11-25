"""Independent risk axes and deterministic verification. Scores are policy levels, not probabilities."""
from dataclasses import dataclass,asdict
import ast,operator,re
from decimal import Decimal,localcontext

@dataclass
class Assessment:
    complexity:int=0
    factual_uncertainty:int=0
    consequence_risk:int=0
    external_verification:bool=False
    tool_execution:bool=False
    verification_required:bool=False
    method:str='none'
    basis:str='ordinary_dialogue_provisional_flash'
    def public(self):return asdict(self)

def arithmetic_expression(text):
    value=text.lower().strip().rstrip('?! .')
    value=re.sub(r'^(?:сколько(?: будет)?|вычисли|посчитай|рассчитай)\s*','',value)
    value=value.replace('×','*').replace('÷','/').replace('−','-').replace(',','.').replace('^','**')
    return value if re.fullmatch(r'[\d\s.+*/()%\-]+',value) and re.search(r'[+*/%\-]',value) else None

def calculate(expression):
    """No eval, functions, names, file/network access or unbounded exponentiation."""
    if len(expression)>200:raise ValueError('expression_limit')
    tree=ast.parse(expression,mode='eval')
    if sum(1 for _ in ast.walk(tree))>60:raise ValueError('expression_limit')
    operations={ast.Add:operator.add,ast.Sub:operator.sub,ast.Mult:operator.mul,ast.Div:operator.truediv,ast.Mod:operator.mod,ast.FloorDiv:operator.floordiv}
    def visit(node):
        if isinstance(node,ast.Constant) and isinstance(node.value,(int,float)) and not isinstance(node.value,bool):
            literal=ast.get_source_segment(expression,node)
            if len(literal)>24:raise ValueError('number_limit')
            return Decimal(literal)
        if isinstance(node,ast.UnaryOp) and isinstance(node.op,(ast.UAdd,ast.USub)):return visit(node.operand)*(-1 if isinstance(node.op,ast.USub) else 1)
        if isinstance(node,ast.BinOp):
            left,right=visit(node.left),visit(node.right)
            if isinstance(node.op,ast.Pow):
                if right!=right.to_integral_value() or abs(right)>12:raise ValueError('power_limit')
                result=left**int(right)
            elif type(node.op) in operations:result=operations[type(node.op)](left,right)
            else:raise ValueError('unsupported_operator')
            if not result.is_finite() or abs(result)>Decimal('1e24'):raise ValueError('result_limit')
            return result
        raise ValueError('unsupported_expression')
    with localcontext() as context:
        context.prec=28;result=visit(tree.body)
    return format(result,'f').rstrip('0').rstrip('.') if '.' in format(result,'f') else format(result,'f')

class RiskAssessment:
    def assess(self,text,context):
        lower=text.lower();topic=lower
        if re.search(r'^(?:а (?:если|ему|ей|тогда|сколько)|почему\??$|сколько ему)',lower):
            topic+=' '+context.get('summary','')[-400:].lower()
        result=Assessment()
        if re.search(r'последн\w*(?:\s+\w+){0,2}\s+(?:сделк|поглощени|приобретени)',lower):
            result.factual_uncertainty=3;result.external_verification=True;result.verification_required=True;result.method='external_sources';result.basis='current_deals_require_sources'
        if re.search(r'(?:какой|какие|что за).*сегодня.*(?:праздник|событи)|сегодня.*(?:праздник|дата)',lower):
            result.factual_uncertainty=3;result.external_verification=True;result.verification_required=True;result.method='external_sources';result.basis='current_calendar_requires_source'
        if re.search(r'\b(?:последн\w*|новейш\w*|сам\w* нов\w*)\s+(?:(?:вышедш\w*|выпущенн\w*|студийн\w*|полнометражн\w*|опубликованн\w*)\s+){0,2}(?:фильм\w*|сериал\w*|альбом\w*|релиз\w*|верси\w*)\b',lower):
            result.factual_uncertainty=3;result.external_verification=True;result.verification_required=True;result.method='external_sources';result.basis='latest_release_requires_source'
        # An ordinary superlative is answerable in conversation. An explicit
        # request to verify it now must not be passed off as a knowledge answer.
        source_request=re.sub(r'^(?:(?:софия|гобот|пожалуйста|скажи|подскажи)[,!:\s]+)*', '',lower.strip())
        source_request=re.sub(r'^(?:(?:ты )?можешь(?: ли)?(?: ты)?|давай)\s+', '',source_request)
        if (re.search(r'^(?:проверь|проверить|поищи|поискать|найди|найти|посмотри|посмотреть|уточни|уточнить)\b[^.!?;\n]{0,160}\b(?:в интернете|в сети|онлайн|по источникам)\b',source_request)
                or re.search(r'^(?:проверь|проверить)\s+(?:(?:этот|эти|такой|такие)\s+)?факт(?:ы|а|ов|у|е|ом|ами|ах)?\b',source_request)):
            result.factual_uncertainty=3;result.external_verification=True;result.verification_required=True;result.method='external_sources';result.basis='explicit_source_check_requested'
        if (re.search(r'\b(?:сейчас|сегодня|на данный момент)\b',lower)
                and re.search(r'\b(?:сам(?:ый|ая|ое|ые)\s+(?:быстр|высок|больш|крупн|длинн|маленьк|дорог|деш[её]в|популярн|мощн)\w*\b(?!\s+(?:способ\w*|метод\w*|при[её]м\w*|пут[ьи]|вариант\w*)\b)|рекорд\w*)\b',lower)):
            result.factual_uncertainty=3;result.external_verification=True;result.verification_required=True;result.method='external_sources';result.basis='current_record_requires_source'
        if arithmetic_expression(lower):return Assessment(1,0,0,False,True,True,'calculator','exact_arithmetic')
        if re.search(r'что (?:мы|я) (?:(?:вчера|раньше|до этого) )?(?:решили|обсуждали|спрашивал)|мо[яию] (?:теплиц|предпочтени)|прошл\w* разговор|как меня зовут',lower):
            return Assessment(0,2,1,False,True,True,'memory_source','personal_history_requires_original_records')
        if re.search(r'лекарств|дозиров|диагноз|реб[её]н.*температур|инвестир|купить акции|ипотек|налог|судебн|электропроводк|утечк\w* газа|ядовит',topic):
            result.consequence_risk=3;result.factual_uncertainty=2;result.external_verification=True;result.verification_required=True;result.method='external_sources';result.basis='high_consequence_requires_verified_guidance'
        if re.search(r'малоизвестн|втор\w* помощник\w* капитана|редк\w* истор|биограф|точн\w* дат|какого числа|в каком году|источник|ссылк|цитат|кто сейчас|актуальн|новост|какая погода|курс (?:доллара|евро)|цен[аы] на|последн\w* событ',lower):
            result.factual_uncertainty=3;result.external_verification=True;result.verification_required=True;result.method='external_sources';result.basis='source_required_fact_or_current_information'
        if re.search(r'докажи|сложн\w* расч[её]т|сравни.*(?:вариант|подход|решени|архитектур)|пошагов\w* (?:провер|вывод)|техническ\w* анализ|математическ\w* доказ|проверь.*(?:расч[её]т|доказательств)|подробн\w* аналитик|оптимизац|интеграл|дифференциальн',lower):result.complexity=2
        return result

class SelectiveVerifier:
    def check(self,assessment,answer,evidence=None):
        if not assessment.verification_required:return {'accepted':True,'method':'not_required','external_sources_checked':False}
        if evidence and evidence.get('abstained') is True:return {'accepted':True,'method':'abstention','external_sources_checked':False,'fact_confirmed':False}
        # Evidence is produced by trusted deterministic tools, never by model self-confidence.
        if evidence and evidence.get('method')==assessment.method and evidence.get('verified') is True:
            canonical=evidence.get('canonical_answer')
            if canonical is None or str(canonical) not in answer:return {'accepted':False,'method':assessment.method,'reason':'answer_not_supported_by_evidence'}
            return {'accepted':True,'method':assessment.method,'external_sources_checked':assessment.external_verification}
        return {'accepted':False,'method':assessment.method,'reason':'required_evidence_unavailable'}
