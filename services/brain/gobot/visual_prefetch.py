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


@dataclass
class VisualStages:
    """Turn-local semantic state. Never shared between profiles or provider sessions."""
    question_topic:Entity|None=None
    provisional_visual:object=None
    answer_topic:Entity|None=None
    refined_visual:object=None
    topic_alignment_status:str='pending'


def stable_visual_chunk(text,final=False):
    """A complete clause, or a sufficiently long prefix without its unfinished word."""
    text=text[:1600]
    ends=list(re.finditer(r'[.!?…](?:\s|$)',text))
    stable=text[:ends[-1].end()] if ends else text if final else re.sub(r'[\w-]+$','',text)
    if len(stable.split())<(4 if final or ends else 8):return ''
    return stable


def answer_entity(expected,query,answer):
    """Conservative local relation extraction, not a universal semantic verifier.

    Only a question-anchored affirmative clause can select a more specific object.
    Unknown relations preserve the provisional scene rather than guessing a topic.
    """
    from .response_alignment import alignment
    if alignment(query,answer)=='suspected_mismatch':return 'mismatch',None
    if PRIVATE_QUERY.search(answer) or PRIVATE.search(answer):return 'unknown',None
    if not expected:
        entity=extract_entity(answer)
        return ('unknown',entity) if entity else ('unknown',None)
    aligned=False
    from .image_query import phrase_lemmas
    question_words=set(phrase_lemmas(query))
    from .speech_formatter import morphology
    forms=[morphology().parse(w)[0] for w in re.findall(r'[\w-]+',expected.label)]
    head=next((p.normal_form for p in forms if p.tag.POS=='NOUN'),None)
    qualifiers=[p.normal_form for p in forms if p.tag.POS=='NOUN' and p.normal_form!=head]
    for clause in re.split(r'[.!?…\n]',answer):
        if re.search(r'хочешь|могу рассказать|можем поговорить|не знаю|не удалось',clause,re.I):continue
        selected=expected.confirm(clause)
        if not selected and head and qualifiers and mentioned(head,clause):
            # Genitive/adjectival relation: «кратер Луны» ↔ «лунный кратер».
            words=[p for w in re.findall(r'[\w-]+',clause) for p in morphology().parse(w)[:2]]
            related=all(mentioned(q,clause) or any(p.tag.POS=='ADJF' and p.normal_form.startswith(q.rstrip('аяоеьй')) and len(q.rstrip('аяоеьй'))>=3 for p in words) for q in qualifiers)
            if related or aligned:selected=expected
        if not selected:continue
        aligned=True
        if selected!=expected:return 'aligned',selected
        # Scientific/technical names in an explicit apposition, not any capital word.
        latin=re.search(r'(?:\(|\b(?:род[ауеом]*|вид[ауеом]*|называется|называют)\s+)([A-Z][a-z]{3,}(?:\s+[a-z]{3,})?)',clause)
        if not latin:
            latin=re.search(r'^\s*([A-Z][a-z]{3,}(?:\s+[a-z]{3,})?)\s*[—–]',clause)
        if latin:
            value=latin[1].strip()
            return 'aligned',Entity(value,value,(value,),method='answer_bound_name')
        # A named instance follows the same noun (crater Tycho, rocket Falcon 9).
        wanted=set(phrase_lemmas(expected.label))
        for named in re.finditer(r'\b([а-яё-]+)\s+([А-ЯЁA-Z][\w-]+(?:\s+\d{1,3})?)',clause):
            if set(phrase_lemmas(named[1]))&wanted:
                value=named[0]
                return 'aligned',Entity(value,value,(value,),method='answer_bound_name')
        if re.search(r'сердц',expected.query,re.I) and re.search(r'кровообращени|кровоток|круг\w*\s+кров',clause,re.I):
            return 'aligned',Entity('Кровообращение человека','Кровообращение человека',('кровообращение','кровоток'),method='answer_process_diagram')
        phrase=noun_phrase(clause,answer=True)
        if phrase and mentioned(expected.anchors[0],phrase) and set(phrase_lemmas(phrase))>wanted and set(phrase_lemmas(phrase))-question_words:
            return 'aligned',Entity(phrase,phrase,(phrase,),method='early_answer_noun_phrase')
    if aligned:return 'aligned',expected
    return 'unknown',None


class TwoStageVisual:
    """Scheduling around the existing attachment pipeline; no new search/cache/provider.

    Stage 1 is public question metadata, explicitly provisional. Paid fallback is
    deferred until a stable aligned answer, and at most once per turn. Stage 2
    cannot overwrite the question with an unbound noun from the model's prose.
    """
    def __init__(self,req,entity,plan,fetch,publish,timeout=8,on_mismatch=None):
        from .device_contract import ScreenPreferences
        self.req=req;self.plan=plan;self.fetch=fetch;self.publish=publish;self.timeout=timeout
        self.on_mismatch=on_mismatch
        self.pref=req.screen_preferences or ScreenPreferences();self.mode=self.pref.visual_strategy
        # New owner policy supersedes the old optional secondary-source chain.
        if self.pref.visual_source_policy=='wikimedia_first':self.pref=self.pref.model_copy(update={'visual_source_policy':'wikimedia_generate'})
        self.req=req.model_copy(update={'screen_preferences':self.pref})
        self.state=VisualStages(question_topic=entity)
        self.answer='';self.final=False;self.closed=False;self.changed=asyncio.Event()
        self.workers=set();self.revision=0;self.published_revision=-1;self.result=None
        self.initial_result=None;self.initial_done=False;self.generation_attempted=False
        self.selected_key=None;self.analysed='';self.keys=set()
        self.diagnostics={'visual_needed':True,'visual_subject':entity.label if entity else None,
            'subject_resolution_method':entity.method if entity else 'awaiting_early_answer',
            'subject_confirmed':False,'visual_strategy':'retrieve','retrieval_started':False,
            'candidate_ready':False,'scene_sent':False,'scene_presented':'unavailable',
            'candidate_rejected_reason':None,'fallback_reason':None,'topic_alignment_status':'pending',
            'refinement_updates':0}
        self.task=asyncio.create_task(self.run())

    def observe_partial(self,text):self.observe(text)
    def observe(self,text,*,final=False):
        if self.closed:return
        self.answer=text;self.final=self.final or final;self.changed.set()
    def finish(self):self.final=True;self.changed.set()

    def initial_plan(self):
        if self.plan.template or self.plan.reason=='ai_illustration':return self.plan
        return self.state.question_topic.plan() if self.state.question_topic else self.plan if self.plan.visual_needed and self.plan.visual_query else None

    def schedule(self,plan,stage,revision,*,generation=False):
        task=asyncio.create_task(self.lookup(plan,stage,revision,generation=generation))
        self.workers.add(task)
        task.add_done_callback(lambda t:(self.workers.discard(t),self.changed.set()))

    async def lookup(self,plan,stage,revision,*,generation):
        try:
            # Same Wikimedia-first cache/search path. No speculative paid work.
            request=self.req if generation else self.req.model_copy(update={'screen_preferences':self.pref.model_copy(update={'generation_allowed':False,'generation_consent':False,'generation_mode':'off'})})
            self.diagnostics['retrieval_started']=True
            mark('visual_prefetch_start',visual_stage=stage)
            result=await self.fetch(request,plan,timeout=self.timeout)
            if stage==1:self.initial_result=result;self.initial_done=True
            if self.closed or self.state.topic_alignment_status=='mismatch':return
            if stage==2 and revision!=self.revision:return
            if stage==1 and self.published_revision>0:return
            if not result or result.frame.metadata.state=='unavailable' or not result.frame.images:
                self.diagnostics['fallback_reason']=result.frame.metadata.reason if result else 'no_candidate';return
            self.diagnostics['candidate_ready']=True;mark('visual_candidate_ready',visual_stage=stage,cache_hit=result.frame.metadata.cache_hit)
            if self.result and [x.asset_id for x in result.frame.images]==[x.asset_id for x in self.result.frame.images]:return
            if plan.visual_type=='diagram':result.frame.metadata.image_fit='contain'
            result.frame.id=frame_id(self.req.turn_id,f'visual-stage-{stage}-{revision}')
            result.frame.metadata.visual_stage='provisional' if stage==1 else 'refined'
            result.frame.metadata.visual_revision=revision
            if stage==1:
                self.state.provisional_visual=result.frame
                result.frame.text='Предварительная иллюстрация темы вопроса. '+result.frame.text
            else:self.state.refined_visual=result.frame
            if await self.publish(result,stage,revision) is False:return
            self.result=result;self.published_revision=revision
            self.diagnostics['scene_sent']=True;mark('visual_scene_sent',visual_stage=stage,revision=revision)
        except asyncio.CancelledError:raise
        except Exception:self.diagnostics['fallback_reason']='optional_visual_unavailable'
        finally:
            if stage==1:self.initial_done=True

    async def run(self):
        try:
            initial=self.initial_plan()
            if initial and self.mode!='answer_only':self.schedule(initial,1,0)
            else:self.initial_done=True
            self.changed.set()
            while not self.closed:
                await self.changed.wait();self.changed.clear()
                stable=stable_visual_chunk(self.answer,self.final)
                if stable and stable!=self.analysed and self.state.topic_alignment_status!='mismatch':
                    self.analysed=stable
                    status,entity=await asyncio.to_thread(answer_entity,self.state.question_topic,self.req.text,stable)
                    self.state.topic_alignment_status=status;self.diagnostics['topic_alignment_status']=status
                    if status=='mismatch':
                        self.diagnostics.update(candidate_rejected_reason='question_answer_topic_mismatch',subject_confirmed=False)
                        if self.on_mismatch:self.on_mismatch()
                        for task in list(self.workers):task.cancel()
                        return self.result
                    if entity and (status=='aligned' or self.state.question_topic is None):
                        self.state.answer_topic=entity
                        self.diagnostics.update(visual_subject=entity.query,subject_resolution_method=entity.method,
                            subject_confirmed=status=='aligned',anchors=list(entity.anchors))
                entity=self.state.question_topic if self.mode=='question_only' else self.state.answer_topic
                if entity and self.state.topic_alignment_status!='mismatch' and self.revision<2:
                    target=entity.plan()
                    if entity.method=='answer_process_diagram':target=target.model_copy(update={'visual_type':'diagram'})
                    key=normal(entity.query)
                    original=normal(self.state.question_topic.query) if self.state.question_topic else ''
                    different=key!=original
                    # No duplicate retrieval/generation for a slight restatement.
                    missing=self.initial_done and not (self.initial_result and self.initial_result.frame.images)
                    permitted=self.pref.visual_source_policy!='wikimedia_only' and self.pref.generation_allowed and self.pref.generation_consent and self.pref.generation_mode!='off' and self.pref.generation_daily_limit>0
                    generation=missing and permitted and self.state.topic_alignment_status=='aligned' and not self.generation_attempted
                    if key not in self.keys and (different and self.mode!='question_only' or self.mode=='answer_only' or generation):
                        self.keys.add(key);self.revision+=1
                        self.diagnostics['refinement_updates']=self.revision if self.mode!='question_only' else 0
                        if generation:self.generation_attempted=True
                        # Refinement may use fallback only after alignment; never generate twice.
                        allow_generation=permitted and self.state.topic_alignment_status=='aligned' and not self.generation_attempted
                        if allow_generation:self.generation_attempted=True
                        self.schedule(target,1 if self.mode=='question_only' else 2,0 if self.mode=='question_only' else self.revision,generation=generation or allow_generation)
                if self.final and not self.workers:break
            return self.result
        finally:
            for task in list(self.workers):task.cancel()
            await asyncio.gather(*self.workers,return_exceptions=True)

    async def close(self):
        self.closed=True;self.changed.set();self.task.cancel()
        await asyncio.gather(self.task,return_exceptions=True)
