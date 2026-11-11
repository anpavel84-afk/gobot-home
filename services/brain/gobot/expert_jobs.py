"""Bounded confirmed expert jobs. Model proposals never authorize execution."""
import asyncio,re,time,json
from dataclasses import dataclass,field
from pathlib import Path
from uuid import uuid4
from .expert_profiles import resolve_profile
from .realtime_budget import RealtimeBudget
from .models import ChatRequest
from .providers import bridge_stream
from .expert_store import ExpertBudget

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
    return bool(re.search(r'\b(?:cli|цли|эксперт\w*|argon|аргон|astra|астр[ауы]|sol|сол[уя]?)\b',text,re.I)
                and re.search(r'переда\w*|адрес\w*|отправ\w*|спроси|подключ\w*|делегир\w*|обрат\w*|пусть.*(?:провер|разбер)',text,re.I))

def profile_in_text(text):
    if re.search(r'\b(?:argon|аргон)\b',text,re.I):return 'ARGON_DEEP'
    if re.search(r'\b(?:astra|астр[ауы])\b',text,re.I):return 'ASTRA_MEDIUM' if re.search(r'\b(?:medium|медиум|средн\w*)\b',text,re.I) else 'ASTRA_HIGH'
    if re.search(r'\b(?:sol|сол|солу|соля)\b',text,re.I):return 'SOL_XHIGH' if re.search(r'\b(?:xhigh|extra high|экстра хай)\b',text,re.I) else 'SOL_HIGH'
    return None

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

class ExpertJobs:
    def __init__(self,session,*,executor=None,budget=None,admission=None):
        self.session=session;self.executor=executor or self.execute
        manager_budget=getattr(getattr(session,'manager',None),'budget',None)
        self.budget=budget or ExpertBudget((manager_budget.root.parent if manager_budget else Path(__file__).resolve().parents[3]/'run')/'realtime-experts')
        self.jobs={};self.pending=None;self.lock=asyncio.Lock()
        self.admission=admission
        self.used_confirmation_turns=set()

    def audit(self,stage,reasons=()):
        recorder=getattr(self.session,'expert_audit',None)
        if recorder:recorder(stage,reasons)

    def active(self):return any(j.state in {'queued','running'} for j in self.jobs.values())

    def authorized_owner(self,job):
        s=self.session
        if s.closed or job.owner!=s.access.effective_scope or job.profile_id!=getattr(s.access,'confirmed_profile_id',None):return False
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
        if owner_public:
            owner_state=self.session.manager.owner_testing.status(self.session.owner_test_binding)
            if owner_state['attempts_today'].get('expert',0)>=owner_state['policy']['expert_jobs_per_day']:reasons.append('owner_expert_daily_limit')
        return {'enabled':not reasons,'blocked_reasons':reasons,'profiles':profile_status() if include_profiles else [],
                'allowed_profiles':getattr(policy,'allowed_profiles',[]),'jobs_remaining':usage['sessions_remaining'],
                'timeout_seconds':getattr(policy,'job_timeout_seconds',90),'jobs':[self.public(j) for j in self.jobs.values()]}

    def owner_public_allowed(self):
        s=self.session
        if not getattr(s,'owner_test_authorized',False) or not s.manager.owner_testing.authorized(s.owner_test_binding):return False
        if s.access.confirmed_profile_id:
            family=s.manager.identity.family
            return bool(family and family.session_valid(s.access.confirmed_profile_id,s.offer.confirmed_profile_epoch)
                        and family.preferences.profile(s.access.confirmed_profile_id)['age']=='adult')
        return True # Device expense authorization, guest/public context only; never person authentication.

    def propose(self,task,profile,turn):
        if not isinstance(task,str) or not 1<=len(task)<=8000:raise ValueError('invalid_expert_task')
        chosen=resolve_profile(profile)
        if not chosen['metadata_verified']:raise ValueError('expert_profile_unavailable')
        requested=profile_in_text(turn.query)
        requested=requested or getattr(self.session.offer,'requested_expert_profile',None)
        if requested and requested!=profile:raise ValueError('explicit_expert_profile_mismatch')
        if len(self.jobs)>=8:raise ValueError('expert_job_capacity')
        if self.pending and self.pending.state=='awaiting_confirmation':self.pending.state='cancelled'
        job=ExpertJob(str(uuid4()),str(uuid4()),task,chosen,len(self.session.turns),self.session.access.effective_scope,self.session.offer.conversation_id)
        job.profile_id=getattr(self.session.access,'confirmed_profile_id',None)
        job.profile_epoch=getattr(self.session.offer,'confirmed_profile_epoch',None)
        job.remember=bool(getattr(self.session.offer,'remember',False) and job.profile_id and job.profile_epoch)
        job.already_explained=turn.answer[:2000]
        # Explicit user request can authorize precisely this task, never a model's paraphrase.
        explicit=profile_in_text(turn.query)==profile and bool(re.search(r'спроси|подключи|передай|пусть.*(?:разбер|провер)',turn.query,re.I))
        previous=getattr(self.session.turns[-2],'query',None) if len(self.session.turns)>1 else None
        job.confirmed=bool(explicit and (task==turn.query or previous and task==previous))
        if job.confirmed:job.confirmation_turn_id=getattr(turn,'id',None)
        self.jobs[job.id]=job;self.pending=job
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
            job.confirmed=True;job.revision=len(self.session.turns);job.confirmation_turn_id=getattr(self.session.current,'id',None)
        elif not (profile_in_text(value) and value==job.task.casefold()):
            # Scope amendment and a new question are not blanket consent.
            job.confirmed=False;job.state='cancelled'

    def public(self,job):
        return {'job_id':job.id,'proposal_id':job.proposal_id,'state':job.state,'task':job.task,
                'expert':{k:job.profile[k] for k in ('profile','requested_label','provider','model','effort')},
                'expires_at':job.expires,'confirmed':job.confirmed,'error':job.error,
                'storage':'confirmed_profile' if job.remember else 'temporary_session','result_ready':bool(job.result),
                'usage_kind':'cli_subscription','usage':job.usage,'timings_ms':job.timings}

    async def start(self,proposal_id,call_id):
        async with self.lock:
            job=next((j for j in self.jobs.values() if j.proposal_id==proposal_id),None)
            if not job or job.owner!=self.session.access.effective_scope:raise ValueError('expert_proposal_not_found')
            if job.call_id:
                if job.call_id==call_id:return job
                raise ValueError('expert_job_already_started')
            if job.state!='awaiting_confirmation' or not job.confirmed or time.time()>job.expires or job.revision!=len(self.session.turns):raise PermissionError('current_user_confirmation_required')
            if job.confirmation_turn_id and job.confirmation_turn_id!=getattr(self.session.current,'id',None):raise PermissionError('current_user_confirmation_required')
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
            if self.session.closed or job.state!='awaiting_confirmation' or job.revision!=len(self.session.turns):raise PermissionError('expert_context_changed')
            if getattr(policy,'owner_full_test',False):
                await asyncio.to_thread(self.session.manager.owner_testing.reserve,self.session.owner_test_binding,'expert',job.id,origin='developer' if getattr(self.session.offer,'developer_acceptance',False) else 'owner')
            reserved=await asyncio.to_thread(self.budget.reserve_session,job.id,True,getattr(self.session.offer,'client_id',None),getattr(self.session,'owner_test_binding',None))
            if not self.authorized_owner(job) or job.state!='awaiting_confirmation' or job.revision!=len(self.session.turns):raise PermissionError('expert_context_changed')
            if job.profile['profile'] not in getattr(reserved,'allowed_profiles',[job.profile['profile']]):raise PermissionError('expert_profile_not_in_budget')
            job.call_id=call_id;job.state='queued'
            self.audit('accepted')
            job.timings['queued']=round((time.monotonic()-job.clock_origin)*1000,2)
            self.used_confirmation_turns.add(confirmation_key)
            self.persist(job)
            # Close the real tool call exactly once with accepted, not a fabricated result.
            await self.session.send({'type':'conversation.item.create','item':{'type':'function_call_output','call_id':call_id,
                'output':json.dumps({'accepted':True,'job_id':job.id,'state':'queued','result_available':False})}})
            job.worker=self.session.spawn(self.run(job))
            self.session.emit('expert_job',job=self.public(job))
            return job

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
        for key in ['messages','retrieved','facts']:
            while tokens(serialize_context(job.task,packet))>job.context_token_limit and packet.get(key):packet[key].pop(0)
        if tokens(serialize_context(job.task,packet))>job.context_token_limit:packet.pop('summary',None)
        if tokens(serialize_context(job.task,packet))>job.context_token_limit:raise ValueError('expert_context_limit')
        return packet

    async def execute(self,job):
        s=self.session
        req=ChatRequest(text=job.task,device_id=s.access.effective_scope,conversation_id=s.access.context_conversation,
                        remember=False,turn_id=job.id,provider=job.profile['provider'],model_id=job.profile['model'],usage_consent=True)
        packet=job.packet or await self.prepare_packet(job)
        result=''
        async for delta in bridge_stream(s.manager.brain.settings,req,packet,expert_profile=job.profile['profile']):
            result+=delta
            if len(result)>job.max_result_characters:raise ValueError('expert_result_limit')
        job.provider_session=packet.get('_provider_session_id')
        usage=packet.get('_provider_usage',{})
        job.usage={k:v for k,v in usage.items() if type(v) is int and v>=0 and k in {'inputTokens','outputTokens','totalTokens','cachedInputTokens','reasoningOutputTokens','input_tokens','output_tokens','total_tokens'}}
        if hasattr(self.budget,'record_cli_usage'):await asyncio.to_thread(self.budget.record_cli_usage,job.id,job.usage)
        return result

    async def run(self,job):
        s=self.session
        try:
            if not self.authorized_owner(job) or job.state=='cancelled':job.state='cancelled';return
            job.state='running';self.persist(job);s.emit('expert_job',job=self.public(job))
            job.timings['running']=round((time.monotonic()-job.clock_origin)*1000,2)
            async with asyncio.timeout(job.timeout_seconds):text=await self.executor(job)
            if s.closed or job.state=='cancelled':return
            if len(text)>job.max_result_characters:raise ValueError('expert_result_limit')
            job.result=normalize_result(text,job.profile);job.state='completed';job.timings['completed']=round((time.monotonic()-job.clock_origin)*1000,2);self.persist(job)
        except asyncio.CancelledError:job.state='cancelled';raise
        except TimeoutError:job.state='timed_out';job.error='expert_timeout'
        except Exception:job.state='failed';job.error='expert_failed_no_retry'
        finally:
            self.persist(job)
            if self.authorized_owner(job):
                if job.state in {'completed','failed','timed_out'}:self.audit(job.state)
                s.emit('expert_job',job=self.public(job))
                await self.return_result(job)

    async def return_result(self,job):
        s=self.session
        if job.returned or not job.call_id or s.closed:return
        job.returned=True
        same_owner=self.authorized_owner(job)
        current=(job.revision==len(s.turns) and same_owner and s.current is not None and not s.current.cancelled)
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
        if current:await s.response()

    async def cancel(self,job_id):
        job=self.jobs.get(job_id)
        if not job or job.owner!=self.session.access.effective_scope:raise ValueError('expert_job_not_found')
        if job.state in {'completed','failed','timed_out','cancelled'}:return self.public(job)
        job.state='cancelled'
        if job.worker:job.worker.cancel();await asyncio.gather(job.worker,return_exceptions=True)
        self.persist(job)
        return self.public(job)

    async def close(self):
        for job in self.jobs.values():
            if job.state in {'awaiting_confirmation','queued','running'}:
                job.state='cancelled'
                if job.worker:job.worker.cancel()
        await asyncio.gather(*(j.worker for j in self.jobs.values() if j.worker),return_exceptions=True)
