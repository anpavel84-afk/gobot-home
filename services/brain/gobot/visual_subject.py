"""Main-response visual decisions; bounded markup is stripped before display/TTS."""
import re
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator

OPEN='<gobot_visual_v1>'
CLOSE='</gobot_visual_v1>'
VISUAL_INSTRUCTIONS=(
    'Выбери экранное сопровождение по смыслу вопроса И своего ответа в этом же ходе. '
    'Для реального предмета/вида предпочитай photo, для объяснения процесса diagram, для беседы avatar. '
    'Закончив предложение с первым упоминанием выбранного объекта, добавь ровно один служебный блок '
    '<gobot_visual_v1>JSON</gobot_visual_v1>. JSON содержит kind, domain и subject. '
    'subject — точное короткое название из уже написанного ответа, со значимыми определениями; не случайное слово. '
    'domain: animal/plant/place/food/object/abstract/none; kind: photo/diagram/avatar. '
    'Для diagram добавь template из lunar_crater/earth_moon/solar_eclipse/volcano/milky_way/tomato_plant/tomato_comparison/dog_comparison. '
    'Не передавай личные данные, ссылки или HTML. Если подходящего публичного объекта нет, выбери avatar с пустым subject. '
    'Блок не часть реплики; после него продолжай обычный ответ. Не обещай, что изображение уже показано.'
)
PRIVATE_QUERY=re.compile(r'\b(?:мо[йяеёю]|моего|моей|наш\w*|семь\w*|мам\w*|пап\w*|сын\w*|доч\w*)\b',re.I)
ANIMAL_QUERY=re.compile(r'\b(?:попуга\w*|птиц\w*|животн\w*|кошк\w*|собак\w*|рыб\w*)\b',re.I)


def normalized(value):return ' '.join(value.casefold().replace('ё','е').split())


class VisualDirective(BaseModel):
    model_config=ConfigDict(extra='forbid')
    kind:Literal['photo','diagram','avatar']
    domain:Literal['animal','plant','place','food','object','abstract','none']
    subject:str=Field(default='',max_length=120)
    template:Literal['lunar_crater','earth_moon','solar_eclipse','volcano','milky_way','tomato_plant','tomato_comparison','dog_comparison']|None=None

    @field_validator('subject')
    @classmethod
    def public_phrase(cls,value):
        if value and (not re.fullmatch(r'[\w -]+',value,re.UNICODE) or '_' in value or len(value.split())>10
                      or re.search(r'\b(?:sk-|token|password|secret|api-key)|[a-z0-9-]{40}',value,re.I)):
            raise ValueError('invalid_public_subject')
        return value.strip()


def grounded(directive,query,answer):
    if PRIVATE_QUERY.search(query):return False
    if directive.kind=='avatar':return True
    subject=normalized(directive.subject);body=normalized(answer)
    if not subject or not re.search(r'(?<!\w)'+re.escape(subject)+r'(?!\w)',body):return False
    # A conspicuous cross-domain mismatch is rejected independently of the model.
    if ANIMAL_QUERY.search(query) and directive.domain!='animal':return False
    if directive.kind=='photo' and directive.domain not in {'animal','plant','place','food','object'}:return False
    position=body.find(subject)
    if re.search(r'\b(?:не|нет)\s+(?:это\s+)?$',body[max(0,position-30):position]):return False
    return directive.kind!='diagram' or directive.template is not None


class VisualMarkupFilter:
    """At most one directive. Invalid/unfinished metadata never becomes speech."""
    def __init__(self):self.buffer='';self.inside=False;self.discard=False;self.seen=False
    def feed(self,delta,final=False):
        self.buffer+=delta;events=[]
        while self.buffer:
            if self.inside:
                end=self.buffer.find(CLOSE)
                if end<0:
                    if len(self.buffer)>1024:self.discard=True;self.buffer=self.buffer[-len(CLOSE):]
                    if final:self.buffer=''
                    break
                raw=self.buffer[:end];self.buffer=self.buffer[end+len(CLOSE):];self.inside=False
                if not self.seen and not self.discard and len(raw)<=1024:
                    try:directive=VisualDirective.model_validate_json(raw)
                    except ValueError:directive=None
                    if directive is not None:events.append(('visual_plan',directive))
                self.seen=True;self.discard=False
                continue
            start=self.buffer.find(OPEN)
            if start>=0:
                if start:events.append(('text',self.buffer[:start]))
                self.buffer=self.buffer[start+len(OPEN):];self.inside=True;continue
            held=0
            for count in range(1,min(len(OPEN),len(self.buffer))+1):
                if self.buffer.endswith(OPEN[:count]):held=count
            safe=len(self.buffer)-held
            if safe:events.append(('text',self.buffer[:safe]));self.buffer=self.buffer[safe:]
            if final:
                if self.buffer and not self.buffer.startswith('<gobot'):events.append(('text',self.buffer))
                self.buffer=''
            break
        return events


async def visual_plan_stream(source,on_plan):
    parser=VisualMarkupFilter();iterator=source.__aiter__()
    try:
        async for delta in iterator:
            for kind,value in parser.feed(delta):
                if kind=='text':yield value
                else:on_plan(value)
        for kind,value in parser.feed('',final=True):
            if kind=='text':yield value
            else:on_plan(value)
    finally:await iterator.aclose()
