"""GoBot deterministic policy. No inference is performed to select a route."""
from dataclasses import dataclass,asdict
import re,time,json
from pathlib import Path
from .processes import AgentError
from .quality import RiskAssessment
from .presentation import PresentationDecision
from .timer_duration import is_timer_duration_reply

@dataclass(frozen=True)
class RouterPolicy:
    prefer_fast_for_simple:bool=True
    heavy_agents_in_auto:bool=False
    auto_escalation_to_heavy:bool=False
    router_extra_llm_call:str='only_when_needed'
    allow_explicit_heavy_selection:bool=True
    fallback_to_expensive:str='require_approval'
    fast_cli_model:str='gemini-3.8-flash-low'
    reasoning_cli_model:str='gemini-3.8-flash-medium'
    manual_google_model:str='gemini-4-argon-medium'
    semantic_enabled:bool=False
    selective_verification:bool=True
    unknown_capability_prefer_safe_route:bool=True
    prefer_deterministic_tools:bool=True

@dataclass
class Decision:
    category:str
    provider:str
    model:str|None
    reason:str
    billing_kind:str
    tool:str|None=None
    requires_permission:bool=False
    router_ms:float=0
    classifier_calls:int=0
    quality:dict|None=None
    def public(self):return asdict(self)

class SmartRouter:
    def __init__(self,policy=None,semantic=None):
        self.policy=policy or RouterPolicy();self.semantic=semantic;self.risk=RiskAssessment()
        self.capabilities=json.loads((Path(__file__).parents[1]/'model-capabilities.json').read_text(encoding='utf-8'))
    def choose(self,req,context,states,*,api_ready=False):
        started=time.perf_counter();text=req.text.strip().lower();mode=req.mode or 'auto';policy=self.policy
        assessment=self.risk.assess(text,context)
        def result(category,provider,model,reason,billing,tool=None,permission=False):
            if model:
                entry=next((r for r in self.capabilities['models'] if r['model']==model and r['provider']==provider),None)
                if not entry:raise AgentError('model_capability_not_registered')
                if not explicit_selection(mode) and 'explicit_selection_only' in entry.get('restrictions',[]):raise AgentError('heavy_model_not_allowed_in_auto')
            return Decision(category,provider,model,reason,billing,tool,permission,(time.perf_counter()-started)*1000,0,assessment.public())
        def explicit_selection(value):return value in {'codex','google','gemini','antigravity'}
        # Diagnostic selection is explicit, never a failure fallback.
        if mode=='mock':return result('FAST_CHAT','mock',None,'explicit_diagnostics','local_mock')
        if context.get('topic',{}).get('outcome')=='ambiguous':return result('TOOL','local',None,'ambiguous_topic_reference','local','clarify_topic')
        files=bool(re.search(r'^(?:гобот[,! ]+)?(?:проверь|исправь|измени|удали|прочитай|отредактируй|проанализируй|подготовь).*?(?:файл|репозитор|локальн|мо[а-яё]*\s+проект|использовани[ея] файлов)',text))
        if files:return result('AGENT','local',None,'file_access_requires_separate_permission','local','file_permission',True)
        if policy.prefer_deterministic_tools and assessment.method=='calculator':return result('TOOL','local',None,'deterministic_calculation','local','calculator')
        if assessment.method=='memory_source':return result('TOOL','local',None,'memory_requires_original_records','local','memory')
        visual=PresentationDecision().detect(req.text)
        if visual and assessment.consequence_risk<2:return result('TOOL','local',None,'server_driven_visual_'+visual.kind,'local','visual')
        if policy.selective_verification and assessment.external_verification:
            return result('REASONING' if assessment.complexity else 'FAST_CHAT','local',None,'required_external_verifier_not_configured','local','verification')
        explicit=mode in {'codex','google','gemini','antigravity'}
        named=re.search(r'(?:спроси|думает|ответь через)\s+(codex|chatgpt|google|gemini|antigravity)',text)
        if named and mode in {'auto','fast','reasoning'}:
            mode='codex' if named[1] in {'codex','chatgpt'} else 'antigravity';explicit=True
        if explicit:
            if not policy.allow_explicit_heavy_selection:raise AgentError('heavy_selection_disabled')
            provider='codex' if mode=='codex' else 'antigravity'
            state=states.get(provider,{})
            if not state.get('available'):raise AgentError(state.get('reason') or 'executor_unavailable')
            model=req.model_id or ('gpt-6.1-sol' if provider=='codex' else policy.manual_google_model)
            return result('AGENT',provider,model,'explicit_model_selection','cli_subscription')
        pending=context.get('pending_action')
        if pending and pending.get('kind')=='timer_duration' and pending.get('expires',0)>time.time() and is_timer_duration_reply(text):
            return result('TOOL','local',None,'pending_timer_duration','local','timer')
        if re.search(r'^(?:гобот[,! ]+)?(?:поставь|установи|запусти|отмени|останови|выключи)\b.*таймер|^таймер(?:\s+на|\s+\d|$)',text):return result('TOOL','local',None,'known_timer_intent','local','timer')
        if text in {'стоп','остановись','хватит','отмена','да','нет','подтверждаю','отмени'}:
            return result('TOOL','local',None,'session_control_without_model','local','control')
        if re.search(r'^(?:гобот[,! ]+)?(?:включи|выключи|останови|открой|закрой|запри|разблокируй).*?(?:музык|свет|ламп|двер|замок|питан)',text):
            return result('TOOL','local',None,'home_tool_requires_configured_permissions','local','home',True)
        if re.search(r'что я (?:вчера |раньше |до этого )?спрашивал|как меня зовут|мои предпочтения',text):
            return result('TOOL','local',None,'memory_read_is_scoped','local','memory')
        reasoning=mode=='reasoning' or assessment.complexity>=2
        # An optional calibrated local semantic hook is used only for unclear requests.
        obvious=bool(re.search(r'^(?:как|кто|что|почему|сколько|расскажи|объясни|привет|спасибо|а |и |ещ[её])\b',text))
        if not reasoning and not obvious and policy.semantic_enabled and self.semantic:
            hint=self.semantic.classify(text,context.get('summary','')[:300])
            reasoning=hint=='REASONING'
        category='REASONING' if reasoning else 'FAST_CHAT'
        state=states.get('antigravity',{})
        if not state.get('available'):raise AgentError(state.get('reason') or 'fast_executor_unavailable')
        return result(category,'antigravity',policy.reasoning_cli_model if reasoning else policy.fast_cli_model,'quality_flash_via_authorized_antigravity','cli_subscription')
