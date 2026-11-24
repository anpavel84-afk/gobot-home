"""Bounded confirmed expert jobs. Model proposals never authorize execution."""
import asyncio,re,time,json
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass,field
from pathlib import Path
from uuid import uuid4
from .expert_profiles import PROFILES,resolve_profile
from .realtime_budget import RealtimeBudget
from .models import ChatRequest
from .providers import bridge_stream
from .expert_store import ExpertBudget
from .expert_stream import AnswerDelta,conversation_binding

EXPERT_DELIVERY_STALL_SECONDS = 5.0

EXPERT_ACTIVITY={'explicit_request','proposal_requested','proposal_created','start_requested','accepted','blocked','completed','failed','timed_out','cancel_requested'}
EXPERT_BLOCKERS={'native_experts_disabled','confirmed_adult_profile_required','expert_quota_consent_required',
    'owner_expert_daily_limit','owner_api_estimate_limit','owner_test_not_authorized',
    'expert_budget_missing_or_expired','expert_budget_exhausted','expert_budget_other_device',
    'confirmation_transcript_pending','current_user_confirmation_required','expert_confirmation_already_used',
    'expert_context_changed','confirmed_adult_required_for_expert','expert_not_in_session_budget',
    'expert_profile_not_in_budget','expert_budget_or_consent_required','realtime_budget_or_consent_required',
    'isolation_not_verified','quota_consent_required','expert_profile_unavailable','explicit_expert_profile_mismatch',
    'expert_context_limit','expert_job_already_started','one_active_expert_job_only','realtime_session_budget_exhausted',
    'realtime_trial_client_not_allowed','tool_validation_or_execution_failed'}

def explicit_expert_request(text):
    """Only a diagnostic intent signal; never authority or a replacement task."""
    value=' '.join(text.casefold().strip().split())
    value=re.sub(r'^(?:(?:софия|гобот|го бот|пожалуйста|а)[, ]+)+','',value)
    value=re.sub(r'^(?:ты можешь|можешь(?: ли)?(?: ты)?|давай)[, ]+','',value)
    return bool(re.search(r'\b(?:cli|цли|codex|кодекс[ау]?|gemini|джемини|гемини|google|гугл|эксперт\w*|argon|аргон|astra|астр[ауы]|sol|сол[уя]?)\b',value)
                and re.match(r'^(?:передай|передать|адресуй|адресовать|отправь|отправить|спроси|спрашивай|подключи|подключить|делегируй|делегировать|обратись|обратиться|попроси|попросить|пусть)\b',value))

def profile_in_text(text):
    if re.search(r'\b(?:argon|аргон)\b',text,re.I):return 'ARGON_DEEP'
    if re.search(r'\b(?:astra|астр[ауы])\b',text,re.I):return 'ASTRA_MEDIUM' if re.search(r'\b(?:medium|медиум|средн\w*)\b',text,re.I) else 'ASTRA_HIGH'
    if re.search(r'\b(?:sol|сол|солу|соля)\b',text,re.I):return 'SOL_XHIGH' if re.search(r'\b(?:xhigh|extra high|экстра хай)\b',text,re.I) else 'SOL_HIGH'
    return None

def require_requested_expert_profile(text,chosen,*,requested_profile=None,requested_provider='configured'):
    """Reject a named routing target that differs from the configured expert.

    This is a constraint, never an intent/consent detector. Provider names in a
    question (for example, comparing Codex with Gemini) do not select an executor.
    The conversation model supplies a constrained semantic provider preference;
    the server compares it without changing its selected profile or grant. The
    additional lexical guard covers only an immediate, initial named addressee.
    """
    if requested_provider not in ('configured','codex','antigravity'):
        raise ValueError('invalid_conversation_mode_arguments')
    if requested_provider!='configured' and requested_provider!=chosen['provider']:
        raise ValueError('explicit_expert_profile_mismatch')
    if requested_profile and requested_profile!=chosen['profile']:
        raise ValueError('explicit_expert_profile_mismatch')
    value=re.sub(r'^(?:(?:софия|гобот|го бот|пожалуйста|давай|ну|а)[, ]+)+','',text.strip(),flags=re.I)
    name=r'(?:codex|кодекс(?:а|у|ом)?|gemini|джемини|гемини|antigravity|антигравити|argon|аргон(?:а|у|ом)?|astra|астр[ауы]|sol|сол[уя]?)'
    level=r'(?:\s+(?:high|hi|хай|medium|медиум|xhigh|extra high|экстра хай))?'
    route=(r'(?:спрос\w*|спраш\w*|попрос\w*|поруч\w*|подключ\w*|'
           r'переда\w*|отправ\w*|адрес\w*|делегир\w*|переключ\w*|перей\w*|перехо\w*|пусть|ask|consult|use|switch(?:\s+to)?)\s+'
           r'(?:пожалуйста[, ]+)?(?:(?:(?:этот|этого|эту|предыдущий|последний|текущий)\s+)?(?:вопрос|задачу|ответ)\s+)?'
           r'(?:(?:у|к|на|в|через|to)\s+)?(?:(?:эксперт(?:а|у|ный)?|режим|модель|модели|cli)\s+){0,2}'
           r'(?:(?:у|к|на|в|через|to)\s+)?(?P<target>'+name+level+r')\b')
    match=re.match(route,value,re.I)
    if match:
        target=match['target']
        if re.match(r'(?:codex|кодекс)',target,re.I):provider='codex';profile=None
        elif re.match(r'(?:gemini|джемини|гемини|antigravity|антигравити)',target,re.I):provider='antigravity';profile=None
        else:
            profile=profile_in_text(target)
            # Inflected Argon is still the same registered profile.
            if profile is None and re.match(r'аргон',target,re.I):profile='ARGON_DEEP'
            provider=PROFILES[profile]['provider'] if profile else None
        if provider and provider!=chosen['provider']:
            raise ValueError('explicit_expert_profile_mismatch')
        if profile:
            if PROFILES[profile]['model']!=chosen['model']:
                raise ValueError('explicit_expert_profile_mismatch')
            if re.search(r'\b(?:high|hi|хай|medium|медиум|xhigh|extra|экстра)\b',target,re.I) and profile!=chosen['profile']:
                raise ValueError('explicit_expert_profile_mismatch')

def explicit_expert_command(text,profile):
    # Only the actual user's imperative can grant this task. Quoted/narrated commands cannot.
    value=re.sub(r'^(?:(?:софия|гобот|го бот)[, ]+)+','',text.strip(),flags=re.I)
    selected=profile_in_text(value)
    return bool((selected==profile or selected is None and explicit_expert_request(value)) and
                re.match(r'^(?:(?:а|пожалуйста|ты)[, ]+)*(?:спроси|спрашивай|подключи|передай|отправь|адресуй|попроси|пусть)\b',value,re.I))

def normalize_result(text,profile):
    text=text.strip()
    if not text or len(text)>24000:raise ValueError('invalid_expert_result')
    summary=re.split(r'\n\s*\n',text,maxsplit=1)[0][:1600]
    return {'conclusion':summary,'display_text':text,'speech_summary':summary,
            'actual_executor':{k:profile[k] for k in ('profile','provider','model','effort')},
            'numbers':re.findall(r'(?<!\w)[+-]?\d+(?:[.,]\d+)?',text),
            'sources_status':'not_independently_verified','assumptions_and_caveats':'Preserve from display_text',
            'trusted_as_instructions':False}

@dataclass
class ExpertJob:
    id:str
    proposal_id:str
    task:str
    profile:dict
    revision:int
    owner:str
    conversation:str
    state:str='awaiting_confirmation'
    expires:float=field(default_factory=lambda:time.time()+120)
    confirmed:bool=False
    call_id:str|None=None
    operation_id:str|None=None
    delegation_id:str|None=None
    provider_session:str|None=None
    result:dict|None=None
    worker:object=None
    returned:bool=False
    error:str|None=None
    profile_id:str|None=None
    profile_epoch:str|None=None
    remember:bool=False
    confirmation_turn_id:str|None=None
    packet:dict=field(default_factory=dict)
    already_explained:str=''
    timeout_seconds:int=90
    max_result_characters:int=24000
    context_token_limit:int=3000
    usage:dict=field(default_factory=dict)
    timings:dict=field(default_factory=dict)
    clock_origin:float=field(default_factory=time.monotonic)
    response_id:str=field(default_factory=lambda:uuid4().hex)
    turn_id:str|None=None
    speech_text:str=''
    played_text:str=''
    spoken_segments:dict=field(default_factory=dict)
    generated_segments:set=field(default_factory=set)
    played_segments:set=field(default_factory=set)
    external_narration:bool=False
    narration_complete:bool=False
    playback_complete:bool=False
    context_recorded:bool=False
    answer_text:str=''
    speech_cancelled:bool=False
    narrator_usage:dict=field(default_factory=dict)
    grant_authorization:str|None=None
    task_source_turn_id:str|None=None
    mode_action_instruction:str=''
    mode_action_authority:object=field(default=None,repr=False,compare=False)

class ExpertJobs:
    def __init__(self,session,*,executor=None,budget=None,admission=None):
        self.session=session;self.executor=executor or self.execute
        manager_budget=getattr(getattr(session,'manager',None),'budget',None)
        self.budget=budget or ExpertBudget((manager_budget.root.parent if manager_budget else Path(__file__).resolve().parents[3]/'run')/'realtime-experts')
        self.jobs={};self.pending=None;self.lock=asyncio.Lock()
        self.admission=admission
        self.used_confirmation_turns=set()
        self.binding=conversation_binding(session)
        self.detached=False;self.closed=False;self.close_reason=None
        self.context_versions={}
        self._context_inflight={}

    @contextmanager
    def hold_context(self,job):
        """Pin RAM ownership while a result write/delivery yields to another task."""
        ident=job.id
        self._context_inflight[ident]=self._context_inflight.get(ident,0)+1
        try:yield
        finally:
            remaining=self._context_inflight[ident]-1
            if remaining:self._context_inflight[ident]=remaining
            else:self._context_inflight.pop(ident,None)

    def detach(self):
        """Detach a lost socket, retaining bounded logical tasks and RAM context."""
        self.detached=True

    async def attach(self,session):
        if self.closed or conversation_binding(session)!=self.binding:
            raise PermissionError('expert_conversation_binding_changed')
        previous=self.session
        if previous is not session and getattr(previous,'experts',None) is self:
            retired=ExpertJobs(previous,budget=self.budget,admission=self.admission)
            retired.closed=True;retired.close_reason='transport_replaced';previous.experts=retired
        self.session=session;self.detached=False;session.experts=self
        self.context_versions.clear()
        await self.sync_context()
        for job in tuple(self.jobs.values()):
            if self.jobs.get(job.id) is not job:continue
            if job.state in {'completed','failed','timed_out'} and not job.returned:
                await self.return_result(job)

    def context_items(self):
        """Bounded untrusted data; only this principal/conversation can read it."""
        return [{'job_id':j.id,'response_id':j.response_id,'task':j.task,
                 'state':j.state,'result':j.result or {'display_text':j.answer_text,'complete':False},'speech_text':j.speech_text,
                 'played_text':j.played_text,'playback_complete':j.playback_complete,
                 'speech_cancelled':j.speech_cancelled,'trusted_as_instructions':False}
                for j in self.jobs.values() if (j.result or j.answer_text) and self.authorized_owner(j)]

    async def sync_context(self,job=None):
        s=self.session
        if self.closed or self.detached or s.closed:return
        for item in self.context_items():
            if job is not None and item['job_id']!=job.id:continue
            target=self.jobs.get(item['job_id'])
            if target is None:continue  # Another awaited item may have allowed pruning.
            version=(item['state'],len(item['result'].get('display_text','')),len(item['speech_text']),len(item['played_text']),item['playback_complete'],item['speech_cancelled'])
            if self.context_versions.get(item['job_id'])==version:continue
            with self.hold_context(target):
                try:
                    hook=getattr(s,'expert_context_synced',None)
                    async with asyncio.timeout(EXPERT_DELIVERY_STALL_SECONDS):
                        if hook:
                            if await hook(target,item) is False:continue
                        else:
                            await s.send({'type':'conversation.item.create','item':{'id':uuid4().hex,
                                'type':'message','role':'user','content':[{'type':'input_text','text':json.dumps(
                                {'kind':'expert_context_snapshot','data':item,'trusted_as_instructions':False},ensure_ascii=False)}]}})
                except Exception:
                    # Keep canonical RAM context pending for an authenticated
                    # attach without detaching a replacement session.
                    if self.session is s and self.jobs.get(target.id) is target and not self.closed:
                        self.detach()
                        target.speech_cancelled=True
                        s.emit('expert_context_pending',job_id=target.id,reason='transport_unavailable')
                    return
                if (self.session is not s or self.jobs.get(target.id) is not target or
                        self.closed or self.detached or s.closed):return
                self.context_versions[target.id]=version
                target.timings['expert_context_synced']=round((time.monotonic()-target.clock_origin)*1000,2)

    async def playback_finished(self,job_id,response_id,segment_id=None):
        job=self.jobs.get(job_id)
        if not job or job.response_id!=response_id or not self.authorized_owner(job):return False
        if job.state=='cancelled' or job.speech_cancelled:return False
        if segment_id is not None:
            if segment_id not in job.generated_segments:return False
            job.played_segments.add(segment_id)
        else:
            if not job.narration_complete:return False
            job.played_segments.update(job.generated_segments)
            job.playback_complete=True
        job.played_text=' '.join(text for ident,text in job.spoken_segments.items() if ident in job.played_segments)
        await self.record_context(job)
        await self.sync_context(job)
        return True

    def audit(self,stage,reasons=()):
        recorder=getattr(self.session,'expert_audit',None)
        if recorder:recorder(stage,reasons)

    def active(self):return any(j.state in {'queued','running'} for j in self.jobs.values())
    def revision(self):
        method=getattr(self.session,'task_revision',None)
        return method() if method else len(self.session.turns)

    def authorized_owner(self,job):
        s=self.session
        if self.closed or (s.closed and not self.detached) or conversation_binding(s)!=self.binding or job.owner!=s.access.effective_scope or job.profile_id!=getattr(s.access,'confirmed_profile_id',None):return False
        if getattr(s,'owner_test_authorized',False) and not s.manager.owner_testing.authorized(s.owner_test_binding):return False
        if job.profile_id:
            return bool(s.manager.identity.family.session_valid(job.profile_id,job.profile_epoch))
        return True # Synthetic unprofiled unit harness; runtime admission requires an adult.

    def persist(self,job):
        store=getattr(getattr(self.session,'manager',None),'expert_store',None)
        if store:store.save(job,job.profile_epoch)

    def status(self,*,include_profiles=True):
        from .expert_profiles import profile_status
        policy=self.budget.policy();usage=self.budget.status();reasons=[]
        if not getattr(self.session.policy,'expert_jobs_allowed',False):reasons.append('native_experts_disabled')
        owner_public=self.owner_public_allowed()
        if not getattr(self.session,'expert_authorized',False) and not owner_public:reasons.append('confirmed_adult_profile_required')
        if not self.session.offer.expert_quota_consent:reasons.append('expert_quota_consent_required')
        if not self.budget.active(policy):reasons.append('expert_budget_missing_or_expired')
        elif policy.allowed_client_id and policy.allowed_client_id!=getattr(self.session.offer,'client_id',None) and not owner_public:reasons.append('expert_budget_other_device')
        elif usage['sessions_remaining']==0:reasons.append('expert_budget_exhausted')
        if owner_public and getattr(self.session,'owner_test_authorized',False):
            owner_state=self.session.manager.owner_testing.status(self.session.owner_test_binding)
            if owner_state['attempts_today'].get('expert',0)>=owner_state['policy']['expert_jobs_per_day']:reasons.append('owner_expert_daily_limit')
        return {'enabled':not reasons,'blocked_reasons':reasons,'profiles':profile_status() if include_profiles else [],
                'allowed_profiles':getattr(policy,'allowed_profiles',[]),'jobs_remaining':usage['sessions_remaining'],
                'timeout_seconds':getattr(policy,'job_timeout_seconds',90),'jobs':[self.public(j) for j in self.jobs.values()]}

    def owner_public_allowed(self):
        s=self.session
        scoped=getattr(s,'scoped_public_expert_allowed',None)
        if scoped and scoped():return True
        if not getattr(s,'owner_test_authorized',False) or not s.manager.owner_testing.authorized(s.owner_test_binding):return False
        if s.access.confirmed_profile_id:
            family=s.manager.identity.family
            return bool(family and family.session_valid(s.access.confirmed_profile_id,s.offer.confirmed_profile_epoch)
                        and family.preferences.profile(s.access.confirmed_profile_id)['age']=='adult')
        return True # Device expense authorization, guest/public context only; never person authentication.

    def prune_terminal_history(self):
        """Keep recent RAM cards without turning eight past jobs into a quota.

        Live jobs and unacknowledged narration remain owned until completion.
        Financial ledgers, persisted authorized results and confirmation replay
        protection are separate and are never deleted here.
        """
        for ident,job in tuple(self.jobs.items()):
            if len(self.jobs)<8:break
            if job.state not in {'completed','failed','timed_out','cancelled'}:continue
            if self._context_inflight.get(ident):continue
            if job.worker is not None and not job.worker.done():continue
            if job.external_narration and not (job.playback_complete or job.speech_cancelled):continue
            if job.state!='cancelled' and not job.returned:continue
            if (not job.remember and job.profile_id is None and
                    job.owner==self.session.access.effective_scope):
                brain=getattr(getattr(self.session,'manager',None),'brain',None)
                if brain:
                    key='expert-'+ident
                    scope=(job.owner,getattr(self.session.access,'context_conversation',job.conversation),
                           getattr(self.session.offer,'profile_epoch',None))
                    with brain.memory.transient_lock:
                        row=brain.memory.transient.get(key)
                        if (row and row.get('status')=='completed' and
                                (row.get('owner'),row.get('conversation'),row.get('epoch'))==scope):
                            brain.memory.transient.pop(key,None)
            self.jobs.pop(ident)
            self.context_versions.pop(ident,None)
            if self.pending is job:self.pending=None

    def _resolved_task_profile(self,task,profile):
        if not isinstance(task,str) or not 1<=len(task)<=8000:raise ValueError('invalid_expert_task')
        if profile not in getattr(self.budget.policy(),'allowed_profiles',[profile]):
            raise PermissionError('expert_profile_not_in_budget')
        chosen=resolve_profile(profile)
        if not chosen['metadata_verified']:raise ValueError('expert_profile_unavailable')
        return chosen

    def _create_proposal(self,task,chosen,turn):
        """Create bounded server state after the caller has checked its route."""
        if getattr(self.budget.policy(),'owner_terminal',False):
            if self.pending and self.pending.state=='awaiting_confirmation':self.pending.state='cancelled'
            self.prune_terminal_history()
        if len(self.jobs)>=8:raise ValueError('expert_job_capacity')
        if self.pending and self.pending.state=='awaiting_confirmation':self.pending.state='cancelled'
        job=ExpertJob(str(uuid4()),str(uuid4()),task,chosen,self.revision(),self.session.access.effective_scope,self.session.offer.conversation_id)
        job.turn_id=getattr(turn,'id',None)
        job.task_source_turn_id=job.turn_id
        job.profile_id=getattr(self.session.access,'confirmed_profile_id',None)
        job.profile_epoch=getattr(self.session.offer,'confirmed_profile_epoch',None)
        job.remember=bool(getattr(self.session.offer,'remember',False) and job.profile_id and job.profile_epoch)
        job.already_explained=turn.answer[:2000]
        self.jobs[job.id]=job;self.pending=job
        return job

    def propose(self,task,profile,turn):
        chosen=self._resolved_task_profile(task,profile)
        requested=profile_in_text(turn.query)
        requested=requested or getattr(self.session.offer,'requested_expert_profile',None)
        if requested and requested!=profile:raise ValueError('explicit_expert_profile_mismatch')
        require_requested_expert_profile(turn.query,chosen)
        job=self._create_proposal(task,chosen,turn)
        # Explicit user request can authorize precisely this task, never a model's paraphrase.
        explicit=explicit_expert_command(turn.query,profile)
        previous=getattr(self.session.turns[-2],'query',None) if len(self.session.turns)>1 else None
        if explicit:
            # Keep an exact permitted source snapshot. A model's task paraphrase never defines consent scope.
            reference_only=bool(re.fullmatch(r'(?:спроси|подключи|передай|отправь|адресуй)\s+(?:(?:этот|предыдущий|последний)\s+(?:вопрос|задачу)\s+)?(?:sol|сол|солу|argon|аргон|astra|астра|астру)(?:\s+(?:high|hi|хай|medium|медиум|extra high|xhigh|экстра хай))?(?:\s+(?:этот вопрос|эту задачу|для глубокого анализа))?[.!? ]*',turn.query,re.I))
            job.task=previous if reference_only and previous and task==previous else turn.query
            if job.task==previous and previous!=turn.query:job.task_source_turn_id=getattr(self.session.turns[-2],'id',None)
        job.confirmed=bool(explicit)
        if job.confirmed:job.confirmation_turn_id=getattr(turn,'id',None)
        return self.public(job)

    def observe(self,text):
        job=self.pending
        if not job or job.state!='awaiting_confirmation':return
        value=' '.join(text.casefold().strip().rstrip('.!?').split())
        if time.time()>job.expires:job.state='timed_out';return
        if re.fullmatch(r'(?:нет|нет[, ]+спасибо|не надо|отмена)',value):job.state='cancelled';return
        if re.fullmatch(r'(?:да|подтверждаю|согласен|да[, ]+(?:argon|аргон|astra|астра|sol|сол)(?: (?:high|hi|хай|medium|медиум|xhigh|extra high|экстра хай))?)',value):
            selected=profile_in_text(value)
            if selected and resolve_profile(selected)['model']==job.profile['model'] and not re.search(r'\b(?:high|hi|хай|medium|медиум|xhigh|extra|экстра)\b',value):selected=job.profile['profile']
            if selected and selected!=job.profile['profile']:job.profile=resolve_profile(selected)
            if not job.profile['metadata_verified']:job.confirmed=False;return
            job.confirmed=True;job.revision=self.revision();job.confirmation_turn_id=getattr(self.session.current,'id',None)
            # The source question survives; narration belongs to the current
            # user decision, including question -> proposal -> explicit yes.
            job.turn_id=job.confirmation_turn_id
        elif not (profile_in_text(value) and value==job.task.casefold()):
            # Scope amendment and a new question are not blanket consent.
            job.confirmed=False;job.state='cancelled'

    def public(self,job):
        return {'job_id':job.id,'proposal_id':job.proposal_id,'state':job.state,'task':job.task,
                'expert':{k:job.profile[k] for k in ('profile','requested_label','provider','model','effort')},
                'expires_at':job.expires,'confirmed':job.confirmed,'error':job.error,
                'storage':'confirmed_profile' if job.remember else 'temporary_session','result_ready':bool(job.result),
                'usage_kind':'cli_subscription','usage':job.usage,'timings_ms':job.timings}

    async def start(self,proposal_id,call_id,*,delegation_id=None):
        async with self.lock:
            if self.closed or self.detached:raise PermissionError('expert_context_changed')
            job=next((j for j in self.jobs.values() if j.proposal_id==proposal_id),None)
            if not job or job.owner!=self.session.access.effective_scope:raise ValueError('expert_proposal_not_found')
            started_key=job.call_id or job.operation_id
            if started_key:
                if started_key==call_id or call_id is None and started_key=='local:'+job.id:return job
                raise ValueError('expert_job_already_started')
            if job.state!='awaiting_confirmation' or not job.confirmed or time.time()>job.expires or job.revision!=self.revision():raise PermissionError('current_user_confirmation_required')
            if job.confirmation_turn_id and job.confirmation_turn_id!=getattr(self.session.current,'id',None):raise PermissionError('current_user_confirmation_required')
            self.require_mode_action_authority(job)
            confirmation_key=getattr(self.session.current,'id',len(self.session.turns))
            if confirmation_key in self.used_confirmation_turns:raise PermissionError('expert_confirmation_already_used')
            if any(j.state in {'queued','running'} for j in self.jobs.values()):raise PermissionError('one_active_expert_job_only')
            if not self.session.offer.expert_quota_consent:raise PermissionError('expert_quota_consent_required')
            if not getattr(self.session,'expert_authorized',False) and not self.owner_public_allowed():raise PermissionError('confirmed_adult_required_for_expert')
            if not getattr(getattr(self.session,'policy',None),'expert_jobs_allowed',False):raise PermissionError('expert_not_in_session_budget')
            policy=await asyncio.to_thread(self.budget.policy)
            if job.profile['profile'] not in getattr(policy,'allowed_profiles',[job.profile['profile']]):raise PermissionError('expert_profile_not_in_budget')
            if self.admission:
                state=self.admission(job.profile)
            elif hasattr(self.session,'manager'):
                from .live_agents import agent_status
                state=(await asyncio.to_thread(agent_status,True)).get(job.profile['provider'],{})
            else:state={'available':True} # Unit harness has no runtime manager/executor admission path.
            if not state.get('available'):raise PermissionError(state.get('reason') or 'expert_isolation_or_provider_unavailable')
            job.timeout_seconds=getattr(policy,'job_timeout_seconds',90)
            job.max_result_characters=getattr(policy,'max_result_characters',24000)
            job.context_token_limit=getattr(policy,'max_context_tokens',3000)
            if hasattr(self.session,'manager'):job.packet=await self.prepare_packet(job)
            if self.session.closed or job.state!='awaiting_confirmation' or job.revision!=self.revision():raise PermissionError('expert_context_changed')
            self.require_mode_action_authority(job)
            if getattr(policy,'owner_full_test',False):
                await asyncio.to_thread(self.session.manager.owner_testing.reserve,self.session.owner_test_binding,'expert',job.id,origin='developer' if getattr(self.session.offer,'developer_acceptance',False) else 'owner')
            self.require_mode_action_authority(job)
            # The budget receives the explicit offer binding, as native input
            # admission does. A session's client-id fallback is only for the
            # separate Owner Full Test ledger, not a phone grant on a board.
            reserved=await asyncio.to_thread(self.budget.reserve_session,job.id,True,getattr(self.session.offer,'client_id',None),getattr(self.session.offer,'owner_test_binding',None))
            if not self.authorized_owner(job) or job.state!='awaiting_confirmation' or job.revision!=self.revision():raise PermissionError('expert_context_changed')
            self.require_mode_action_authority(job)
            if job.profile['profile'] not in getattr(reserved,'allowed_profiles',[job.profile['profile']]):raise PermissionError('expert_profile_not_in_budget')
            job.grant_authorization=reserved.authorization
            if call_id is None:job.operation_id='local:'+job.id
            elif hasattr(self.session,'expert_accepted'):job.operation_id=call_id;job.delegation_id=delegation_id
            else:job.call_id=call_id
            job.state='queued'
            self.audit('accepted')
            job.timings['queued']=round((time.monotonic()-job.clock_origin)*1000,2)
            self.used_confirmation_turns.add(confirmation_key)
            self.persist(job)
            # Close the real tool call exactly once with accepted, not a fabricated result.
            if hasattr(self.session,'expert_accepted'):await self.session.expert_accepted(job)
            elif call_id is not None:
                await self.session.send({'type':'conversation.item.create','item':{'type':'function_call_output','call_id':call_id,
                    'output':json.dumps({'accepted':True,'job_id':job.id,'state':'queued','result_available':False})}})
            # A transport reader must not own a paid logical job's lifetime.
            job.worker=asyncio.create_task(self.run(job),name='expert:'+job.id)
            self.session.emit('expert_job',job=self.public(job))
            return job

    async def start_local(self,task,profile,turn):
        """Application-only entry after explicit, server-owned expert selection.

        No fabricated provider call ID is created. A model proposal cannot set the
        selection hook; it is implemented by the authenticated input coordinator.
        """
        if turn is not self.session.current:raise PermissionError('expert_context_changed')
        selected=getattr(self.session,'expert_input_authorized',None)
        if not explicit_expert_command(turn.query,profile) and not (selected and selected(turn)):
            raise PermissionError('current_user_confirmation_required')
        proposal=self.propose(task,profile,turn)
        job=self.pending
        job.task=turn.query;job.confirmed=True;job.confirmation_turn_id=getattr(turn,'id',None)
        return await self.start(proposal['proposal_id'],None)

    def require_mode_action_authority(self,job):
        """Recheck application-owned semantic consent only during admission."""
        capabilities=getattr(self.session,'capabilities',None)
        if capabilities is not None and not capabilities.enabled_now('expert'):
            raise PermissionError('capability_disabled_by_owner')
        authority=job.mode_action_authority
        if authority is None:return
        s=self.session;turn=getattr(s,'current',None)
        checker=getattr(s,'expert_mode_action_authorized',None)
        source=next((item for item in s.turns if getattr(item,'id',None)==job.task_source_turn_id),None)
        request=getattr(source,'req',None)
        if (self.closed or self.detached or s.closed or turn is None or getattr(turn,'cancelled',False) or
                turn.id!=job.turn_id or turn.query!=job.mode_action_instruction or
                source is None or source.query!=job.task or getattr(source,'local_control',False) or
                request is None or request.text!=job.task or request.device_id!=job.owner or
                request.conversation_id!=s.access.context_conversation or request.profile_epoch!=getattr(s.offer,'profile_epoch',None) or
                getattr(authority,'task',None)!=job.task or getattr(authority,'profile',None)!=job.profile['profile'] or
                getattr(authority,'source_turn_id',None)!=job.task_source_turn_id or
                getattr(authority,'instruction',None)!=job.mode_action_instruction or getattr(authority,'turn_id',None)!=job.turn_id or
                getattr(authority,'profile_snapshot',None)!=tuple(job.profile[key] for key in ('profile','provider','model','effort')) or
                not callable(checker) or checker(authority) is not True or not self.authorized_owner(job)):
            raise PermissionError('expert_context_changed')

    async def start_mode_action(self,task,profile,turn,*,authority,source_turn_id=None):
        """One server-proven semantic decision, with no second confirmation.

        The model supplies no task, profile or authority object to this method.
        The authenticated controller resolves the exact current/previous question
        and binds its one-shot authority to the current user instruction. A model
        suggestion still uses propose()/observe(), never this entry point.
        """
        s=self.session
        checker=getattr(s,'expert_mode_action_authorized',None)
        if (authority is None or turn is not s.current or not callable(checker) or checker(authority) is not True):
            raise PermissionError('current_user_confirmation_required')
        chosen=self._resolved_task_profile(task,profile)
        require_requested_expert_profile(turn.query,chosen,
            requested_profile=getattr(s.offer,'requested_expert_profile',None),
            requested_provider=getattr(authority,'requested_provider','configured'))
        source_turn_id=source_turn_id or getattr(turn,'id',None)
        # Validate the complete immutable payload before creating a pending card.
        probe=ExpertJob('','',task,chosen,self.revision(),s.access.effective_scope,s.offer.conversation_id,
            turn_id=getattr(turn,'id',None),task_source_turn_id=source_turn_id,
            mode_action_instruction=turn.query,mode_action_authority=authority,
            profile_id=getattr(s.access,'confirmed_profile_id',None),
            profile_epoch=getattr(s.offer,'confirmed_profile_epoch',None))
        self.require_mode_action_authority(probe)
        job=self._create_proposal(task,chosen,turn)
        job.task_source_turn_id=source_turn_id
        job.mode_action_instruction=turn.query;job.mode_action_authority=authority
        # A generated fragment is not evidence that the user heard it. Existing
        # scoped memory supplies only its recorded, acknowledged dialogue extent.
        job.already_explained=''
        job.confirmed=True;job.confirmation_turn_id=turn.id
        try:
            return await self.start(job.proposal_id,None)
        except BaseException:
            if job.state=='awaiting_confirmation':
                job.state='cancelled';job.confirmed=False
            raise
        finally:
            # After acceptance the ordinary exact grant/owner checks own the
            # worker lifetime. Consuming the action cannot cancel paid narration.
            job.mode_action_authority=None

    async def prepare_packet(self,job):
        s=self.session
        req=ChatRequest(text=job.task,device_id=s.access.effective_scope,conversation_id=s.access.context_conversation,
                        remember=False,turn_id=job.id,provider=job.profile['provider'],model_id=job.profile['model'],usage_consent=True)
        context=await asyncio.to_thread(s.manager.brain.memory.context,req)
        packet=await asyncio.to_thread(s.manager.brain.context_manager.pack,req.text,context,'REASONING')
        # Bound the whole packet; never slice JSON into invalid/unattributed fragments.
        from .context_manager import tokens,serialize_context
        packet['dialogue_state']={'expert_deliverable':'Give checkable conclusions, arguments, assumptions, source status, uncertainty and caveats. No hidden chain-of-thought. Current facts require supplied sources; another model is not independent factual evidence.',
                                 'already_explained_by_gobot':job.already_explained[:1000]}
        if job.mode_action_instruction:
            packet['dialogue_state']['expert_deliverable']+=' The server has already accepted the requested expert handoff. Answer the substantive question in the exact user utterance, applying the current user request to its source question; do not claim you must switch conversation mode yourself or ask for the same handoff again.'
            packet['dialogue_state']['mode_action_request']={
                'current_user_instruction':job.mode_action_instruction,
                'instruction_turn_id':job.turn_id,'source_question_turn_id':job.task_source_turn_id,
                'origin':'current_user_request','trusted_as_instructions':False}
        for key in ['messages','retrieved','facts']:
            while tokens(serialize_context(job.task,packet))>job.context_token_limit and packet.get(key):packet[key].pop(0)
        if tokens(serialize_context(job.task,packet))>job.context_token_limit:packet.pop('summary',None)
        packet_tokens=tokens(serialize_context(job.task,packet))
        if packet_tokens>job.context_token_limit:raise ValueError('expert_context_limit')
        if job.mode_action_instruction and '_context_meta' in packet:
            # Include the complete current instruction in the existing bound;
            # neither it nor the source question is silently shortened.
            meta=packet['_context_meta'];meta['packet_tokens']=packet_tokens
            for key in ('dialogue_state','messages','retrieved','facts','summary'):
                meta['section_tokens'][key]=tokens(packet[key]) if packet.get(key) else 0
        return packet

    async def execute(self,job):
        s=self.session
        req=ChatRequest(text=job.task,device_id=s.access.effective_scope,conversation_id=s.access.context_conversation,
                        remember=False,turn_id=job.id,provider=job.profile['provider'],model_id=job.profile['model'],usage_consent=True)
        cli_deadline=asyncio.get_running_loop().time()+job.timeout_seconds
        # Admission normally supplies this packet before reserving quota. Keep
        # a fallback preparation inside the same original CLI deadline too.
        async with asyncio.timeout_at(cli_deadline):
            packet=job.packet or await self.prepare_packet(job)
        result=''
        # The producer owns the original CLI deadline. A slow speaker never
        # stretches the CLI request or blocks reading its already-paid result.
        # Both text copies are bounded by max_result_characters; every queued
        # element contains >=1 character and <=200 identifier characters.
        pending=deque();changed=asyncio.Event();producer_done=False;producer_error=None
        async def produce():
            nonlocal result,producer_done,producer_error
            iterator=bridge_stream(s.manager.brain.settings,req,packet,expert_profile=job.profile['profile'])
            received=0
            try:
                async with asyncio.timeout_at(cli_deadline):
                    async for delta in iterator:
                        received+=1
                        if received%64==0:await asyncio.sleep(0)
                        if not self.authorized_owner(job) or job.state=='cancelled':raise asyncio.CancelledError()
                        if isinstance(delta,AnswerDelta):
                            if delta.job_id not in {None,job.id}:raise ValueError('expert_delta_job_mismatch')
                            if not delta.speakable:continue
                            if delta.item_id is not None and (not isinstance(delta.item_id,str) or len(delta.item_id)>200):
                                raise ValueError('expert_delta_metadata_invalid')
                        elif job.profile['provider'] in {'codex','antigravity'}:
                            raise ValueError('expert_answer_metadata_missing')
                        else:delta=AnswerDelta(str(delta),job_id=job.id,verified=False)
                        if not delta:continue
                        if len(result)+len(delta)>job.max_result_characters:raise ValueError('expert_result_limit')
                        # Copy only verified bounded fields, not arbitrary
                        # attributes attached by a transport implementation.
                        safe=AnswerDelta(str(delta),item_id=delta.item_id,phase=delta.phase,
                            job_id=job.id,verified=delta.verified,completed=bool(delta.completed))
                        result+=str(safe);job.answer_text=result;pending.append(safe);changed.set()
                        job.timings.setdefault('codex_first_answer_delta',round((time.monotonic()-job.clock_origin)*1000,2))
                job.timings['codex_result_complete']=round((time.monotonic()-job.clock_origin)*1000,2)
            except BaseException as error:
                producer_error=error
                raise
            finally:
                producer_done=True;changed.set()
                if hasattr(iterator,'aclose'):await iterator.aclose()
        async def source():
            while True:
                if producer_error is not None:raise producer_error
                if pending:
                    yield pending.popleft()
                    continue
                if producer_done:return
                changed.clear()
                await changed.wait()

        async def render(options):
            if options is None:
                async for _ in source():pass
                return
            from .pipeline import expert_voiced_events
            job.external_narration=bool(options.get('speech') is not None and options.get('paid_tts_consent'))
            def speech_allowed():
                target=self.session
                current=getattr(target,'current',None)
                return bool(not self.detached and not target.closed and not job.speech_cancelled and
                    job.revision==self.revision() and current is not None and not current.cancelled and self.authorized_owner(job))
            events=expert_voiced_events(options.get('speech'),source(),job_id=job.id,
                conversation_id=job.conversation,turn_id=job.turn_id or job.id,response_id=job.response_id,
                voice=options.get('voice','marin'),paid_tts_consent=options.get('paid_tts_consent',False),
                tts_character_limit=options.get('tts_character_limit'),usage_sink=job.narrator_usage,
                speech_allowed=speech_allowed)
            try:
                async for event in events:
                    data=event['data'];kind=event['type']
                    if kind=='expert_sentence':
                        job.spoken_segments[data['segment_id']]=data['text']
                        job.speech_text=' '.join(job.spoken_segments.values())
                        job.timings.setdefault('first_speakable_chunk',round((time.monotonic()-job.clock_origin)*1000,2))
                    elif kind=='audio_chunk':job.timings.setdefault('narrator_first_audio',round((time.monotonic()-job.clock_origin)*1000,2))
                    elif kind=='audio_segment_done':
                        job.generated_segments.add(data['segment_id'])
                        await self.record_context(job)
                        await self.sync_context(job)
                    elif kind=='audio_stop':
                        job.narration_complete=data['reason']=='finished'
                        if data['reason']=='interrupted':job.speech_cancelled=True
                    target=self.session
                    if not self.detached and not target.closed and self.authorized_owner(job):
                        deliver=getattr(target,'expert_stream_event',None)
                        if deliver:
                            try:await asyncio.wait_for(deliver(job,event),EXPERT_DELIVERY_STALL_SECONDS)
                            except Exception:
                                # No client can indefinitely retain a producer
                                # or narrator. Preserve the paid CLI result,
                                # suppress speech, and never retry either call.
                                self.detach();job.speech_cancelled=True
            finally:await events.aclose()

        producer=asyncio.create_task(produce(),name='expert-source:'+job.id)
        renderer=None
        try:
            hook=getattr(s,'expert_stream_started',None)
            try:options=await asyncio.wait_for(hook(job),EXPERT_DELIVERY_STALL_SECONDS) if hook and not self.detached else None
            except Exception:
                options=None
                s.emit('narration_unavailable',job_id=job.id,reason='narrator_preparation_failed')
            renderer=asyncio.create_task(render(options),name='expert-narrator:'+job.id)
            done,_=await asyncio.wait({producer,renderer},return_when=asyncio.FIRST_COMPLETED)
            if producer in done:await producer  # Fail/timeout stops narration immediately.
            await renderer
            await producer
        finally:
            for task in (producer,renderer):
                if task and not task.done():task.cancel()
            await asyncio.gather(*(t for t in (producer,renderer) if t),return_exceptions=True)
            pending.clear()
        job.provider_session=packet.get('_provider_session_id')
        usage=packet.get('_provider_usage')
        if not isinstance(usage,dict):usage={}
        job.usage={k:v for k,v in usage.items() if type(v) is int and v>=0 and k in {'inputTokens','outputTokens','totalTokens','cachedInputTokens','reasoningOutputTokens','input_tokens','output_tokens','total_tokens'}}
        if job.usage and hasattr(self.budget,'record_cli_usage'):await asyncio.to_thread(self.budget.record_cli_usage,job.id,job.usage)
        return result

    async def record_context(self,job):
        """Full answer plus audible extent lives in Brain's existing RAM history."""
        brain=getattr(getattr(self.session,'manager',None),'brain',None)
        if (not brain or not (job.result or job.answer_text) or
                self.jobs.get(job.id) is not job or not self.authorized_owner(job)):return
        req=ChatRequest(text=job.task,device_id=job.owner,
            conversation_id=getattr(self.session.access,'context_conversation',job.conversation),
            profile_epoch=getattr(self.session.offer,'profile_epoch',None),remember=False,
            turn_id='expert-'+job.id)
        payload=json.dumps({'kind':'expert_result','job_id':job.id,'result':job.result or {'display_text':job.answer_text,'complete':False},
                           'speech_text':job.speech_text,'played_text':job.played_text,
                           'playback_complete':job.playback_complete,'speech_cancelled':job.speech_cancelled,
                           'trusted_as_instructions':False},ensure_ascii=False)
        with self.hold_context(job):
            if not job.context_recorded:
                await asyncio.to_thread(brain.memory.start,req)
                await asyncio.to_thread(brain.memory.finish,req,'completed',payload,job.profile['provider'],[])
                job.context_recorded=True
            else:await asyncio.to_thread(brain.memory.complete_native_continuation,req,payload,job.profile['provider'],[])

    async def run(self,job):
        s=self.session
        watcher=None
        try:
            if not self.authorized_owner(job) or job.state=='cancelled':job.state='cancelled';return
            job.state='running';self.persist(job);s.emit('expert_job',job=self.public(job))
            job.timings['running']=round((time.monotonic()-job.clock_origin)*1000,2)
            async def watch_authorization():
                while True:
                    await asyncio.sleep(.25)
                    try:
                        active_policy=await asyncio.to_thread(self.budget.policy)
                        allowed=bool(active_policy.enabled and active_policy.authorization==job.grant_authorization and
                                     job.profile['profile'] in getattr(active_policy,'allowed_profiles',[job.profile['profile']]))
                    except Exception:allowed=False
                    if not allowed or not self.authorized_owner(job):
                        job.error='expert_context_changed'
                        if job.worker:job.worker.cancel()
                        return
            watcher=asyncio.create_task(watch_authorization())
            if self.executor==self.execute:
                # execute() independently bounds its CLI reader; its bounded
                # narrator may continue after a successful CLI has finished.
                text=await self.executor(job)
            else:
                # Existing non-streaming custom executors keep their original
                # request deadline. No admission or model allowance is widened.
                async with asyncio.timeout(job.timeout_seconds):text=await self.executor(job)
            if not self.authorized_owner(job) or job.state=='cancelled':job.state='cancelled';return
            if len(text)>job.max_result_characters:raise ValueError('expert_result_limit')
            job.result=normalize_result(text,job.profile);job.state='completed';job.timings['completed']=round((time.monotonic()-job.clock_origin)*1000,2);self.persist(job)
            await self.record_context(job)
        except asyncio.CancelledError:job.state='cancelled';raise
        except TimeoutError:job.state='timed_out';job.error='expert_timeout'
        except Exception:job.state='failed';job.error='expert_failed_no_retry'
        finally:
            if watcher:watcher.cancel();await asyncio.gather(watcher,return_exceptions=True)
            if job.state=='cancelled':
                job.speech_cancelled=True
                await self.record_context(job)
            self.persist(job)
            if self.authorized_owner(job):
                if job.state in {'completed','failed','timed_out'}:self.audit(job.state)
                self.session.emit('expert_job',job=self.public(job))
                await self.return_result(job)

    async def return_result(self,job):
        try:await self._return_result(job)
        except Exception:
            # Unknown delivery is not retried as another paid response. The
            # canonical result remains available through context_items/reattach.
            job.error='expert_result_delivery_unconfirmed'
            self.session.emit('expert_result_pending',job_id=job.id,reason='transport_unavailable')

    async def _return_result(self,job):
        s=self.session
        if job.returned or not (job.call_id or job.operation_id) or s.closed or self.detached:return
        job.returned=True
        same_owner=self.authorized_owner(job)
        current=(job.revision==self.revision() and same_owner and s.current is not None and not s.current.cancelled)
        if hasattr(s,'expert_voice_current'):current=current and s.expert_voice_current(job)
        if hasattr(s,'expert_completed'):
            if same_owner and job.result:s.emit('expert_result',job=self.public(job),result=job.result,voice_deferred=not current)
            if same_owner and job.result:await self.sync_context(job)
            await s.expert_completed(job,current)
            return
        output={'job_id':job.id,'state':job.state}
        if current and job.result:output['result']=job.result
        else:output['result_withheld']='Context changed or task unavailable; do not invent an expert conclusion.'
        # The original tool call already received accepted. Do not send a second output.
        # A new user-data item is a supported conversation notification, never an instruction.
        if current:
            notice={'kind':'expert_job_completed','origin_call_id':job.call_id,'data':output,'trusted_as_instructions':False}
            await s.send({'type':'conversation.item.create','item':{'id':uuid4().hex,'type':'message','role':'user',
                'content':[{'type':'input_text','text':json.dumps(notice,ensure_ascii=False)}]}})
            job.timings['result_notified']=round((time.monotonic()-job.clock_origin)*1000,2);self.persist(job)
        if same_owner and job.result:s.emit('expert_result',job=self.public(job),result=job.result,voice_deferred=not current)
        if current and not job.external_narration:await s.response()

    async def cancel(self,job_id):
        job=self.jobs.get(job_id)
        if not job or job.owner!=self.session.access.effective_scope:raise ValueError('expert_job_not_found')
        if job.state in {'completed','failed','timed_out','cancelled'}:
            if job.external_narration and not job.playback_complete:
                job.speech_cancelled=True
                hook=getattr(self.session,'expert_cancelled',None)
                if hook and not self.detached and not self.session.closed:await hook(job)
                await self.record_context(job);await self.sync_context(job)
            return self.public(job)
        job.state='cancelled'
        job.speech_cancelled=True
        if job.worker:job.worker.cancel();await asyncio.gather(job.worker,return_exceptions=True)
        hook=getattr(self.session,'expert_cancelled',None)
        if hook and not self.detached and not self.session.closed:await hook(job)
        await self.record_context(job);await self.sync_context(job)
        self.persist(job)
        return self.public(job)

    async def close(self,reason='conversation_closed'):
        if reason in {'transport_disconnected','sideband_closed','socket_rotation','transport_rotation'}:
            self.detach();return
        self.closed=True;self.close_reason=reason
        for job in self.jobs.values():
            if job.state in {'awaiting_confirmation','queued','running'}:
                job.state='cancelled'
                if job.worker:job.worker.cancel()
        await asyncio.gather(*(j.worker for j in self.jobs.values() if j.worker),return_exceptions=True)
        # Permanent data, if explicitly authorized, already lives in ExpertStore.
        # Clear temporary context when the logical conversation ends.
        for job in self.jobs.values():
            if not job.remember:
                brain=getattr(getattr(self.session,'manager',None),'brain',None)
                if brain:
                    with brain.memory.transient_lock:brain.memory.transient.pop('expert-'+job.id,None)
                job.task='';job.packet.clear();job.result=None;job.answer_text='';job.speech_text='';job.played_text=''
                job.spoken_segments.clear();job.generated_segments.clear();job.played_segments.clear()
