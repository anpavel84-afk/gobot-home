"""Request-side entity extraction, speculative media fetch and text-side confirmation."""
import asyncio
import re
from dataclasses import dataclass

from .answer_illustration import social
from .image_query import ALIASES,installed_entries,normal
from .presentation import frame_id
from .presentation_planner import ResponsePresentationPlan
from .speech_formatter import morphology
from .telemetry import mark
from .visual_subject import PRIVATE_QUERY,mentioned


@dataclass(frozen=True)
class Entity:
    query:str
    label:str
    anchors:tuple[str,...]
    group:str=''

    def plan(self):
        return ResponsePresentationPlan(visual_needed=True,visual_priority='helpful',visual_type='image_card',
            visual_strategy='retrieve',visual_query=self.query,subject_label=self.label,subject_source='request',
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
SKIP={'вопрос','ответ','вид','род','порода','разновидность','пример','размер','цвет','страна',
      'год','месяц','день','время','жизнь','пожалуйста','смысл','отличие','разница','помощь'}

def extract_entity(question):
    """Only a short public noun phrase can leave the host, never a raw question."""
    if PRIVATE_QUERY.search(question) or PRIVATE.search(question) or social(question):return None
    text=normal(question)
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
    # Public common nouns only. Keep adjacent attributive adjectives, reject
    # competing heads rather than searching for the first incidental location.
    morph=morphology();entries=installed_entries();heads={};adjectives=[]
    for match in re.finditer(r'[А-Яа-яЁё-]+|[^А-Яа-яЁё\s]+',question[:450]):
        word=match[0];forms=morph.parse(word);form=forms[0]
        # «белые» can be a plural noun in isolation. Before a noun preserve
        # its adjectival reading, otherwise «белые медведи» becomes all bears.
        if form.tag.POS=='NOUN' and not entries.get(normal(form.normal_form)):
            form=next((p for p in forms if p.tag.POS=='ADJF'),form)
        lemma=normal(form.normal_form)
        if form.tag.POS=='ADJF' and 'Apro' not in form.tag and lemma not in {'обычный','такой','какой','другой','этот'}:
            adjectives.append((word,form));continue
        if (form.tag.POS=='NOUN' and lemma not in SKIP and not {'Name','Surn','Patr','Geox'}&form.tag.grammemes
                and (lemma in ALIASES or len(entries.get(lemma,{}).get('senses',[]))==1)):
            prefix=[]
            for _,adj in adjectives[-2:]:
                agree=adj.inflect({'nomn','sing',form.tag.gender}) if form.tag.gender else None
                prefix.append(agree.word if agree else adj.normal_form)
            name=' '.join([*prefix,lemma])
            heads[lemma]=Entity(name,name,(name,))
        adjectives=[]
    return next(iter(heads.values())) if len(heads)==1 else None


class SpeculativePhoto:
    """Only a confirmed entity may release a ready image into this turn."""
    def __init__(self,req,entity,fetch,timeout,warmed=None):
        self.req=req;self.entity=entity;self.fetch=fetch;self.timeout=timeout
        self.confirmation=asyncio.get_running_loop().create_future()
        self.lookup=warmed or self.start(entity)
        self.task=asyncio.create_task(self.run())
        self.selected=None
        self.checked=0
        self.wants_specific=bool(re.search(r'пород|разновидност|\bвид[а-яё]*\b',req.text,re.I))

    def start(self,entity):
        async def lookup():
            mark('visual_prefetch_start',entity_revision=int(entity!=self.entity))
            result=await self.fetch(self.req,entity.plan(),timeout=self.timeout)
            if result and result.frame.images:mark('visual_candidate_ready',cache_hit=result.frame.metadata.cache_hit)
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
        selected=self.entity.confirm(sentence)
        if self.wants_specific and selected==self.entity and self.entity.group in {'parrots','porcini'} and not final:return
        if selected:
            self.selected=selected
            mark('visual_entity_confirmed')
            self.confirmation.set_result(selected)

    def finish(self):
        if not self.confirmation.done():self.confirmation.set_result(None)

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
                result.frame.id=frame_id(self.req.turn_id,'attachment')
                mark('visual_prefetch_released',cache_hit=result.frame.metadata.cache_hit)
            return result
        finally:
            self.lookup.cancel()
            await asyncio.gather(self.lookup,return_exceptions=True)

    async def close(self):
        self.task.cancel();self.lookup.cancel()
        await asyncio.gather(self.task,self.lookup,return_exceptions=True)
