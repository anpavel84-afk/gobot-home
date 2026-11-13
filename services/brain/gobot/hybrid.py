"""Owner web-only dispatcher over the existing Brain. No provider calls here."""
import asyncio,hashlib,json,re,time
from dataclasses import dataclass,field
from uuid import uuid4
from .models import ChatRequest
from .quick_intents import resolve_quick,normalize,QuickIntent
from .timer_duration import timer_seconds
from .hybrid_contract import RouteDecision,AnswerEnvelope,IntentCandidate,ActionResult
from .hybrid_skills import ALIASES
from .weather_answer import envelope as weather_envelope

@dataclass
class Frame:
    domain:str
    slots:dict
    expires:float
    answer:AnswerEnvelope|None=None

@dataclass
class Conversation:
    scope:tuple
    id:str=field(default_factory=lambda:uuid4().hex)
    frame:Frame|None=None
    media:str|None=None
    epoch:int=0
    expires:float=field(default_factory=lambda:time.monotonic()+1800)
    lock:asyncio.Lock=field(default_factory=asyncio.Lock)

class Hybrid:
    def __init__(self,brain):
        self.brain=brain;self.conversations={};self.operations={};self.clock=time.monotonic
        self.semantic_plugin=None # No authorized semantic provider is installed for this preview.

    def open(self,scope):
        self.conversations={k:v for k,v in self.conversations.items() if v.expires>self.clock()}
        if len(self.conversations)>=128:raise ValueError('preview_capacity')
        c=Conversation(tuple(scope));self.conversations[c.id]=c;return c

    def owned(self,ident,scope):
        c=self.conversations.get(ident)
        if not c or c.scope!=tuple(scope) or c.expires<=self.clock():raise PermissionError('preview_scope_or_epoch_expired')
        return c

    def issue(self,conversation,scope):
        c=self.owned(conversation,scope)
        self.operations={k:v for k,v in self.operations.items() if v['expires']>self.clock()}
        if len(self.operations)>=512:raise ValueError('preview_operation_capacity')
        ident=uuid4().hex;self.operations[ident]={'scope':c.scope,'conversation':c.id,'expires':self.clock()+300,'hash':None,'result':None}
        return ident

    @staticmethod
    def tool_owner(scope):return 'hybrid:'+hashlib.sha256(json.dumps(list(scope)).encode()).hexdigest()[:32]

    def request(self,c,text,turn):
        principal,client,epoch=c.scope
        return ChatRequest(device_id=principal,client_id=client,profile_epoch=epoch,
            conversation_id=c.id,turn_id=turn,text=text,remember=False,client_kind='device')

    def contextual(self,c,req):
        tools=req.model_copy(update={'device_id':self.tool_owner(c.scope)})
        context=self.brain.memory.context(tools)
        if c.frame and c.frame.expires<=self.clock():c.frame=None
        if c.frame and c.frame.domain=='weather':context.update(weather_followup=True,weather_last_request=c.frame.slots)
        context.update(self.brain.configuration.weather_query_context(req))
        return context

    def classify(self,text,context,c):
        value=normalize(text)
        from .quality import arithmetic_expression
        if arithmetic_expression(value):return ('EXECUTE_TOOL',QuickIntent('calculation','calculator',{}),None)
        if re.match(r'^(?:что будет|что произойдет),? если\b',value):return ('NO_ACTION',None,'hypothetical_not_command')
        if re.fullmatch(r'отмена|нет(?:,? спасибо)?|не надо',value):
            return ('MEDIA_CONTROL',None,'cancel_pending' if context.get('pending_action') or context.get('weather_query_pending') else 'stop')
        if c.frame and c.frame.domain=='weather' and value in {'точно','а точно','сколько точно','точная температура'}:
            return ('EXECUTE_TOOL',QuickIntent('weather_exact','settings',c.frame.slots),None)
        if c.frame and c.frame.domain=='weather' and re.fullmatch(r'почему ты советуешь зонт(?:ик)?|почему нужен зонт|можно (?:ли )?купаться|а на пляж',value):
            return ('EXECUTE_TOOL',QuickIntent('weather_explain','weather_explain',{'beach':'купаться' in value or 'пляж' in value}),None)
        # Questions, quotations and negated actions are not imperative proposals.
        if re.match(r'^(?:не (?!мог)|никогда не |я (?:купил|сказал|прочитал)|(?:как|что значит|что означает|можно ли|зачем) (?:поставить|включить|отменить|[«"“]))',value):return ('NO_ACTION',None,'negated_or_mentioned')
        if re.match(r'^(?:расскажи|прочитай) (?:мне )?(?:сказку|историю|рассказ)',value):return ('START_STORYTELLER',None,'explicit_story_request')
        if re.match(r'^(?:включи|поставь) (?:песню|музыку|альбом)\b',value):return ('ABSTAIN_UNAVAILABLE',None,'music_adapter_not_connected')
        if any(q in value for q in '«»"“”'):return ('NO_ACTION',None,'quoted_command_not_executed')
        if re.fullmatch(r'стоп|остановись|хватит|пауза|продолжай|продолжи|читай дальше|возобнови|повтори',value):
            if value in {'стоп','остановись','хватит'}:return ('MEDIA_CONTROL',None,'stop')
            if c.media=='story':return ('MEDIA_CONTROL',None,'pause' if value=='пауза' else 'resume' if value!='повтори' else 'repeat')
            return ('CLARIFY_SLOT',None,'no_unique_media_target')
        if re.fullmatch(r'отмена|нет(?:,? спасибо)?|не надо',value):
            return ('MEDIA_CONTROL',None,'cancel_pending' if context.get('pending_action') or context.get('weather_query_pending') else 'stop')
        if re.fullmatch(r'да|согласен|подтверждаю|на (?:\d+|пять|десять)',value) and not context.get('pending_action') and not context.get('weather_query_pending'):
            return ('CLARIFY_SLOT',None,'no_current_pending')
        if re.fullmatch(r'да|согласен|подтверждаю',value) and (context.get('pending_action') or context.get('weather_query_pending')):return ('CLARIFY_SLOT',None,'typed_slot_required')
        if re.search(r'личн(?:ый|ом|ую|ой)|мои файлы|удали .*файл|парол',value):return ('ABSTAIN_UNAVAILABLE',None,'private_access_not_authorized')
        pending=context.get('pending_action') or {}
        if pending.get('kind')=='timer_duration' and pending.get('payload',{}).get('default_unit')=='minutes':
            bare=re.fullmatch(r'(?:на )?([а-я\d ]{1,50})',value)
            seconds=timer_seconds(bare[1]+' минут') if bare else None
            if seconds:return ('EXECUTE_TOOL',QuickIntent('timer_start','timer',{'operation':'start','seconds':seconds}),None)
        if re.search(r'\b(?:если|только если|когда|либо|или)\b|,? нет,? на ',value) and re.search(r'таймер|поставь|включи',value):return ('CLARIFY_SLOT',None,'whole_plan_ambiguous')
        quick=resolve_quick(text,context)
        if quick:
            if quick.executor=='quick_clarify' or quick.status=='rejected':return ('CLARIFY_SLOT',quick,quick.reason or 'parameters_required')
            if quick.status=='unavailable' or quick.executor in {'unavailable','skill_readiness'}:return ('ABSTAIN_UNAVAILABLE',quick,'adapter_not_connected')
            if quick.executor=='settings' and quick.slots.get('operation','').startswith('weather_'):return ('EXECUTE_TOOL',quick,'weather')
            if quick.executor=='settings' and quick.slots.get('operation')=='patch' and set(quick.slots.get('patch',{}))=={'voice'} and set(quick.slots['patch']['voice'])=={'volume'}:
                return ('EXECUTE_TOOL',quick,'browser_volume') if 0<=quick.slots['patch']['voice']['volume']<=1 else ('CLARIFY_SLOT',None,'volume_out_of_range')
            if quick.executor=='settings':return ('ABSTAIN_UNAVAILABLE',quick,'preview_settings_write_not_enabled')
            if quick.executor not in {'timer','timer_status','clock','calculator','utility','quick_help','dialogue_end','control','pending_decline'}:return ('ABSTAIN_UNAVAILABLE',quick,'preview_adapter_not_connected')
            return ('EXECUTE_TOOL',quick,None)
        if re.fullmatch(r'(?:а )?(?:завтра|послезавтра|сегодня|в субботу|на выходных)|на \w+|еще \w+ минут',value):return ('CLARIFY_SLOT',None,'task_context_required')
        from .timer_duration import is_timer_duration_reply
        if is_timer_duration_reply(value) or re.fullmatch(r'нет[, ]+на \w+',value):return ('CLARIFY_SLOT',None,'task_context_required')
        if re.search(r'\b(?:эксперт|astra|argon|sol|астра|аргон|сол)\b',value):return ('DELEGATE_EXPERT_A',None,'expert_requires_existing_confirmed_flow')
        if re.match(r'^(?:включи|выключи|открой|закрой|запусти|поставь|создай|удали|закажи|напомни|найди фото|покажи картинку|сгенерируй)\b',value):return ('ABSTAIN_UNAVAILABLE',None,'adapter_not_connected')
        if not value:return ('NO_ACTION',None,'empty_input')
        return ('OPEN_CONVERSATION_C',None,'explicit_provider_activation_required')

    def plan(self,text,context,c):
        value=normalize(text)
        two=re.fullmatch(r'поставь (?:два|2) одинаковых таймера по (.+)',value)
        if two:
            seconds=timer_seconds(two[1])
            return [('EXECUTE_TOOL',QuickIntent('timer_start','timer',{'operation':'start','seconds':seconds}),None)]*2 if seconds else [('CLARIFY_SLOT',None,'duration_required')]
        # A bounded grammar, not split('и'): connector must introduce a complete second task.
        compound=re.fullmatch(r'(.+?)\s+(?:и|затем)\s+((?:поставь|установи|объясни|расскажи|какая|который|удали|включи|отмени)\b.+)',value)
        if compound and not any(q in value for q in '«"“'):
            return [self.classify(compound[1],context,c),self.classify(compound[2],{},c)]
        return [self.classify(text,context,c)]

    async def dispatch(self,body,scope):
        c=self.owned(body.conversation_id,scope);op=self.operations.get(body.operation_id)
        if not op or op['scope']!=tuple(scope) or op['conversation']!=c.id or op['expires']<=self.clock():raise PermissionError('server_operation_required')
        digest=hashlib.sha256(body.model_dump_json().encode()).hexdigest()
        async with c.lock:
            if op['hash'] and op['hash']!=digest:raise ValueError('operation_payload_conflict')
            if op['result']:return op['result'].model_copy(update={'replay':True})
            op['hash']=digest;c.epoch+=1;c.expires=self.clock()+1800
            op['text']=body.text
            started=time.perf_counter();req=self.request(c,body.text,body.operation_id);context=self.contextual(c,req)
            decision=RouteDecision(decision_id=uuid4().hex,operation_id=body.operation_id,turn_id=req.turn_id,
                route_type='NO_ACTION',answer=AnswerEnvelope(presentation_epoch=c.epoch))
            if body.truncated:
                plan=[('CLARIFY_SLOT',None,'truncated_input_not_executed')]
            elif body.mode!='hybrid':plan=[('OPEN_CONVERSATION_B' if body.mode=='b' else 'OPEN_CONVERSATION_C',None,'explicit_provider_activation_required')]
            else:plan=self.plan(body.text,context,c)
            spans=[(0,len(body.text))]*len(plan)
            source_match=re.search(r'\s+(?:и|затем)\s+(?=(?:поставь|установи|объясни|расскажи|какая|который|удали|включи|отмени)\b)',body.text,re.I)
            if len(plan)==2 and source_match:spans=[(0,source_match.start()),(source_match.end(),len(body.text))]
            decision.candidates=[IntentCandidate(skill_id=ALIASES.get(q.intent,q.intent) if q else route.lower(),
                proposed_args=q.slots if q else {},spans=[spans[i]],provenance='context_frame' if c.frame else 'user_text') for i,(route,q,_) in enumerate(plan)]
            # Validate the WHOLE plan before any side effect.
            forbidden=next(((route,q,why) for route,q,why in plan if route!='EXECUTE_TOOL' or q and (q.status=='needs_parameters' or q.intent=='timer_start' and q.slots.get('seconds') is None)),None)
            if len(plan)>1 and forbidden:
                decision.route_type='CLARIFY_SLOT';decision.reason='whole_plan_requires_confirmation_or_parameters'
                decision.answer.speech_text='Сначала уточним весь запрос: вторая часть или параметры пока недоступны. Таймер не запущен.'
            else:
                for i,(route,quick,why) in enumerate(plan):
                    decision.route_type=route;decision.reason=why
                    action_id=body.operation_id+':'+str(i)
                    if route=='EXECUTE_TOOL':
                        toolreq=req.model_copy(update={'device_id':self.tool_owner(c.scope),'turn_id':action_id})
                        pending=context.get('pending_action')
                        if pending and (not quick or quick.intent not in {'timer_start','pending_decline'}):self.brain.memory.settle_pending(toolreq,'superseded')
                        if quick.executor=='weather_explain':
                            from .local_tools import ToolResult
                            text='Температура воздуха не доказывает безопасность купания. Данных о течении, волнах и качестве воды здесь нет.' if quick.slots.get('beach') else 'Правило совета: взять зонт при вероятности осадков не ниже сорока процентов. Это вероятность, а не факт дождя; без данных о вероятности совет не подтверждён.'
                            result=ToolResult(text,evidence={'verified':True,'method':'weather_rule'})
                            answer=AnswerEnvelope(speech_text=text,canonical_facts={'rule_threshold_percent':40},presentation_epoch=c.epoch)
                        elif quick.executor=='settings':
                            result=await self.brain.configuration.execute(req,quick.slots)
                            answer=weather_envelope(result,exact=bool(re.search(r'точн',body.text)),epoch=c.epoch)
                            if why=='browser_volume':
                                c.frame=None;answer.display_data={'volume':quick.slots['patch']['voice']['volume']}
                            elif (result.evidence or {}).get('verified'):
                                c.frame=Frame('weather',result.evidence.get('weather_request',quick.slots),self.clock()+90,answer)
                            elif not (result.evidence or {}).get('reason','').startswith('weather_location'):c.frame=None
                        else:
                            c.frame=None
                            if quick.intent=='timer_start' and quick.slots.get('seconds') is not None:
                                result=await asyncio.to_thread(self.brain.tools.start_timer_once,toolreq,quick.slots['seconds'],action_id)
                            else:result=await asyncio.to_thread(self.brain.tools.execute,quick.executor,toolreq,{**quick.slots,'intent':quick.intent,'status':quick.status})
                            frame=self.brain.visual.timer(toolreq,result.widget).model_dump() if result.widget else None
                            if quick.intent=='timer_start' and quick.slots.get('seconds') is None:
                                self.brain.memory.set_pending(toolreq,'timer_duration',{'default_unit':'minutes'})
                                result.text='На сколько минут поставить таймер? Можно указать секунды или часы.'
                            from .realtime_russian import spoken_fields
                            answer=AnswerEnvelope(speech_text=spoken_fields(result.text)['spoken_text'],canonical_facts=result.evidence or {},
                                display_data={'frame':frame} if frame else {},presentation_epoch=c.epoch)
                        evidence=result.evidence or {};needs=evidence.get('needs_parameters') or evidence.get('reason','').startswith('weather_location')
                        status='not_run' if needs else 'failed' if evidence.get('abstained') else 'success'
                        if needs:decision.route_type='CLARIFY_SLOT'
                        decision.results.append(ActionResult(operation_id=body.operation_id,action_id=action_id,status=status,
                            verified_data=evidence,evidence={'executor':quick.executor},timestamp=time.time(),error_code=evidence.get('reason')))
                        if len(plan)>1:answer.speech_text=decision.answer.speech_text+' '+answer.speech_text
                        decision.answer=answer;decision.approved=status=='success'
                    elif route=='MEDIA_CONTROL':
                        if why=='cancel_pending':
                            self.brain.memory.settle_pending(req.model_copy(update={'device_id':self.tool_owner(c.scope)}),'cancelled')
                            self.brain.configuration.clear_weather_query(req)
                        decision.approved=True;decision.answer.speech_text='Хорошо.'
                        decision.answer.display_data={'media_command':why}
                    elif route=='START_STORYTELLER':
                        c.frame=None
                        decision.reason='select_story_or_authorized_generation'
                        decision.answer.speech_text='Выберите готовый тестовый рассказ или передайте свой текст. Новая история требует отдельно доступного текстового адаптера.'
                    elif route in {'OPEN_CONVERSATION_B','OPEN_CONVERSATION_C'}:
                        c.frame=None;self.brain.memory.settle_pending(req.model_copy(update={'device_id':self.tool_owner(c.scope)}),'superseded')
                        decision.handover={'engine':'b' if route.endswith('_B') else 'c','query':body.text,
                            'requires_manual_activation':True,'trusted_instructions':False,'native_transcript_pipeline_preserved':True}
                        decision.answer.speech_text='Для открытого разговора выберите доступный разговорный режим. Платная сессия автоматически не открыта.'
                    elif route=='CLARIFY_SLOT':decision.answer.speech_text='Уточните задачу или её параметры. Без актуального контекста действие не выполнено.'
                    elif route=='NO_ACTION':
                        c.frame=None
                        if re.match(r'^не (?:ставь|запускай|включай)',normalize(body.text)):
                            self.brain.memory.settle_pending(req.model_copy(update={'device_id':self.tool_owner(c.scope)}),'cancelled')
                        decision.answer.speech_text='Команда не выполнялась. Это отрицание, упоминание или вопрос о действии.'
                    else:
                        c.frame=None;decision.answer.speech_text='Этот канал не подключён или требует отдельного допуска. Действие не выполнено.'
            decision.timings_ms={'dispatch':round((time.perf_counter()-started)*1000,3)}
            op['result']=decision;return decision
