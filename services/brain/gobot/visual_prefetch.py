"""Request-side entity extraction, speculative media fetch and text-side confirmation."""
import asyncio
import re
from dataclasses import dataclass

from .answer_illustration import social
from .image_query import normal
from .presentation import frame_id
from .presentation_planner import ResponsePresentationPlan
from .semantic_visual import noun_phrase
from .telemetry import mark
from .visual_subject import PRIVATE_QUERY,mentioned


@dataclass(frozen=True)
class Entity:
    query:str
    label:str
    anchors:tuple[str,...]
    group:str=''
    method:str='request_noun_phrase'

    def plan(self):
        return ResponsePresentationPlan(visual_needed=True,visual_priority='helpful',visual_type='image_card',
            visual_strategy='retrieve',visual_query=self.query,subject_label=self.label,subject_source='context' if self.method=='active_visual_subject' else 'answer' if self.method=='early_answer_noun_phrase' else 'request',
            subject_resolution_method=self.method,
            origin='implicit',reason='speculative_entity_photo')

    def confirm(self,sentence):
        if re.search(r'\b(?:не о|не про|речь не|не имеет отношения|не относится|не является|не похож|это не|вовсе не|не гриб\w*)\b',sentence,re.I):
            return None
        # Disambiguate the two senses of «лисички» on both sides of the exchange.
        if self.group=='chanterelles':
            if not re.search(r'гриб|cantharellus',sentence,re.I):return None
            if re.search(r'ложн\w*\s+лисич|лисиц|лисят',sentence,re.I):return None
        if self.group=='parrots':
            match=re.search(r'\bсолнечн\w*\s+аратинг\w*\b',sentence,re.I)
            if match and mentioned(match[0],sentence):
                return Entity('солнечная аратинга','Солнечная аратинга',(match[0],))
        if self.group=='porcini':
            match=re.search(r'\b(?:елов\w* бел\w* гриб\w*|бел\w* гриб\w* елов\w*)\b',sentence,re.I)
            if match and mentioned(match[0],sentence):
                return Entity('еловый белый гриб','Еловый белый гриб',(match[0],))
        if any(mentioned(anchor,sentence) for anchor in self.anchors):return self
        return None


PRIVATE=re.compile(r'https?://|[@/\\]|\b(?:адрес|парол\w*|ключ доступа|телефон\w*|профил\w*|аккаунт\w*|фамили\w*|переписк\w*|документ\w*)\b',re.I)
SKIP={'вопрос','ответ','вид','род','герой','персонаж','порода','разновидность','пример','размер','цвет','страна',
      'год','месяц','день','время','жизнь','пожалуйста','смысл','отличие','разница','помощь'}

def extract_entity(question):
    """Only a short public noun phrase can leave the host, never a raw question."""
    if PRIVATE_QUERY.search(question) or PRIVATE.search(question) or social(question):return None
    text=normal(question)
    if re.search(r'человеч\w*\s+сердц|сердц\w*\s+человек',text):
        return Entity('Сердце человека','Сердце человека',('сердце человека','человеческое сердце'))
    if re.search(r'\bлисич(?:к\w*|ек)\b',text):
        if not re.search(r'ложн\w*\s+лисич|лисят|лисиц|хвост|нора|звер|лиса\b',text):
            return Entity('Лисичка (род грибов)','Лисички',('лисичка','Cantharellus'),'chanterelles')
        return None
    if re.search(r'\b(?:паук\w*|пауч(?:ок|ки|к\w+))\b',text):
        return Entity('Пауки','Пауки',('паук','паучок'),'spiders')
    if re.search(r'\bпопуга\w*',text):
        return Entity('Попугаеобразные','Попугаи',('попугай','попугаеобразные'),'parrots')
    conure=re.search(r'\bсолнечн\w*\s+аратинг\w*\b',text)
    if conure:return Entity('солнечная аратинга','Солнечная аратинга',(conure[0],'солнечная аратинга'))
    if re.search(r'\bбел\w* гриб\w*',text):
        return Entity('Белый гриб','Белый гриб',('белый гриб',),'porcini')
    if re.search(r'\braspberry\s+pi\b',text) and not re.search(r'\b(?:zero|pico|[0-9]+)\b',text):
        return Entity('Raspberry Pi','Raspberry Pi',('Raspberry Pi',))
    phrase=noun_phrase(question)
    if not phrase:return None
    # An adjectival head is also an anchor when the answer drops a genitive
    # qualifier already explicit in the question; keep the full search subject.
    words=phrase.split();anchors=[phrase]
    from .speech_formatter import morphology
    for index,word in enumerate(words):
        if morphology().parse(word)[0].tag.POS=='NOUN':
            if index>=1 and index+1<len(words):anchors.append(' '.join(words[:index+1]))
            break
    return Entity(phrase,phrase,tuple(anchors))


def planned_entity(question,plan,context=None):
    entity=extract_entity(question)
    if (entity is None and plan.reason=='recipe_reference_photo' and plan.visual_query
            and not PRIVATE_QUERY.search(question) and not PRIVATE.search(question)):
        return Entity('блюдо '+plan.visual_query,plan.visual_query,(plan.visual_query,))
    if entity is None and not PRIVATE_QUERY.search(question) and not PRIVATE.search(question):
        active=(context or {}).get('active_visual_subject')
        topic=(context or {}).get('topic',{})
        if active and topic.get('outcome') not in {'new_topic','ambiguous'}:
            entity=Entity(active['subject'],active['subject'],tuple(active.get('anchors') or [active['subject']]),method='active_visual_subject')
    return entity


class SpeculativePhoto:
    """Only a confirmed entity may release a ready image into this turn."""
    def __init__(self,req,entity,fetch,timeout,warmed=None):
        self.req=req;self.entity=entity;self.fetch=fetch;self.timeout=timeout
        self.confirmation=asyncio.get_running_loop().create_future()
        self.diagnostics={'visual_needed':True,'visual_subject':entity.label if entity else None,
            'subject_resolution_method':entity.method if entity else 'awaiting_early_answer',
            'visual_strategy':'retrieve','retrieval_started':False,'candidate_ready':False,
            'candidate_rejected_reason':None,'scene_sent':False,'scene_presented':'unavailable',
            'fallback_reason':None,'subject_confirmed':False}
        self.lookup=warmed or (self.start(entity) if entity else None)
        if warmed:self.diagnostics['retrieval_started']=True
        self.task=asyncio.create_task(self.run())
        self.selected=None
        self.checked=0
        self.wants_specific=bool(re.search(r'пород|разновидност|\bвид[а-яё]*\b',req.text,re.I))

    def start(self,entity):
        async def lookup():
            self.diagnostics['retrieval_started']=True
            mark('visual_prefetch_start',entity_revision=int(entity!=self.entity))
            result=await self.fetch(self.req,entity.plan(),timeout=self.timeout)
            if result and result.frame.images:
                self.diagnostics['candidate_ready']=True
                mark('visual_candidate_ready',cache_hit=result.frame.metadata.cache_hit)
            else:self.diagnostics['fallback_reason']=result.frame.metadata.reason if result else 'no_candidate'
            return result
        return asyncio.create_task(lookup())

    def observe_partial(self,text):
        if self.confirmation.done() or len(text)-self.checked<28:return
        self.checked=len(text)
        # Discard the unfinished word. Only the current clause can confirm an entity.
        clause=re.split(r'[.!?…\n]',text[-400:])[-1]
        stable=re.sub(r'[\w-]+$','',clause)
        if len(stable.split())>=4:self.observe(stable)

    def observe(self,sentence,*,final=False):
        if self.confirmation.done():return
        if self.entity is None:
            # Resolve only the first substantive clause; never an incidental
            # suggestion after a whole answer. This uses no extra model call.
            if not PRIVATE_QUERY.search(sentence) and not PRIVATE.search(sentence):
                phrase=noun_phrase(sentence,answer=True)
                if phrase:
                    self.entity=Entity(phrase,phrase,(phrase,),method='early_answer_noun_phrase')
                    self.lookup=self.start(self.entity)
        selected=self.entity.confirm(sentence) if self.entity else None
        if (not selected and self.entity and self.entity.method=='active_visual_subject'
                and re.match(r'^(?:теперь|перейд[её]м|поговорим|расскажу)\s+(?:к|о|об|про)\s+',sentence,re.I)):
            transition=re.sub(r'^(?:теперь|перейд[её]м|поговорим|расскажу)\s+(?:к|о|об|про)\s+','',sentence,flags=re.I)
            if not PRIVATE_QUERY.search(transition) and not PRIVATE.search(transition):
                phrase=noun_phrase(transition,answer=True)
                if phrase:
                    selected=Entity(phrase,phrase,(phrase,),method='early_answer_noun_phrase')
        if self.wants_specific and selected==self.entity and self.entity.group in {'parrots','porcini'} and not final:return
        if selected:
            self.selected=selected
            self.diagnostics.update(visual_subject=selected.query,subject_resolution_method=selected.method,subject_confirmed=True,anchors=list(selected.anchors))
            mark('visual_entity_confirmed')
            self.confirmation.set_result(selected)

    def finish(self):
        if not self.confirmation.done():
            self.diagnostics.update(candidate_rejected_reason='subject_not_grounded_in_answer',fallback_reason='subject_not_confirmed')
            self.confirmation.set_result(None)

    async def run(self):
        try:
            selected=await self.confirmation
            if selected is None:return None
            if selected.query!=self.entity.query:
                self.lookup.cancel()
                await asyncio.gather(self.lookup,return_exceptions=True)
                self.lookup=self.start(selected)
            result=await self.lookup
            if result and result.frame.images:
                self.diagnostics['candidate_ready']=True
                self.diagnostics['visual_strategy']=result.frame.metadata.visual_strategy
            if result and result.frame.images:
                result.frame.id=frame_id(self.req.turn_id,'attachment')
                mark('visual_prefetch_released',cache_hit=result.frame.metadata.cache_hit)
            return result
        finally:
            if self.lookup:
                self.lookup.cancel()
                await asyncio.gather(self.lookup,return_exceptions=True)

    async def close(self):
        self.task.cancel()
        if self.lookup:self.lookup.cancel()
        await asyncio.gather(*[t for t in (self.task,self.lookup) if t],return_exceptions=True)
