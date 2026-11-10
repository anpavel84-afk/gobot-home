"""Bounded confirmed expert jobs. Model proposals never authorize execution."""
import asyncio,re,time
from dataclasses import dataclass,field
from pathlib import Path
from uuid import uuid4
from .expert_profiles import resolve_profile
from .realtime_budget import RealtimeBudget
from .models import ChatRequest
from .providers import bridge_stream

def profile_in_text(text):
    if re.search(r'\b(?:argon|аргон)\b',text,re.I):return 'ARGON_DEEP'
    if re.search(r'\b(?:astra|астр[ауы])\b',text,re.I):return 'ASTRA_HIGH'
    if re.search(r'\b(?:sol|сол|солу)\b',text,re.I):return 'SOL_XHIGH'
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

class ExpertJobs:
    def __init__(self,session,*,executor=None,budget=None):
        self.session=session;self.executor=executor or self.execute
        self.budget=budget or RealtimeBudget(Path(__file__).resolve().parents[3]/'run/realtime-experts')
        self.jobs={};self.pending=None;self.lock=asyncio.Lock()

    def propose(self,task,profile,turn):
        if not isinstance(task,str) or not 1<=len(task)<=8000:raise ValueError('invalid_expert_task')
        chosen=resolve_profile(profile)
        if not chosen['metadata_verified']:raise ValueError('expert_profile_unavailable')
        if len(self.jobs)>=8:raise ValueError('expert_job_capacity')
        if self.pending and self.pending.state=='awaiting_confirmation':self.pending.state='cancelled'
        job=ExpertJob(str(uuid4()),str(uuid4()),task,chosen,len(self.session.turns),self.session.access.effective_scope,self.session.offer.conversation_id)
        # Explicit user request can authorize precisely this task, never a model's paraphrase.
        explicit=profile_in_text(turn.query)==profile and bool(re.search(r'спроси|подключи|передай|пусть.*(?:разбер|провер)',turn.query,re.I))
        job.confirmed=bool(explicit and task==turn.query)
        self.jobs[job.id]=job;self.pending=job
        return self.public(job)

    def observe(self,text):
        job=self.pending
        if not job or job.state!='awaiting_confirmation':return
        value=' '.join(text.casefold().strip().rstrip('.!?').split())
        if time.time()>job.expires:job.state='timed_out';return
        if re.fullmatch(r'(?:нет|нет[, ]+спасибо|не надо|отмена)',value):job.state='cancelled';return
        if re.fullmatch(r'(?:да|подтверждаю|согласен|да[, ]+(?:argon|аргон|astra|астра|sol|сол)(?: (?:high|extra high|экстра хай))?)',value):
            selected=profile_in_text(value)
            if selected and selected!=job.profile['profile']:job.profile=resolve_profile(selected)
            job.confirmed=True;job.revision=len(self.session.turns)
        elif not (profile_in_text(value) and value==job.task.casefold()):
            # Scope amendment and a new question are not blanket consent.
            job.confirmed=False;job.state='cancelled'

    def public(self,job):
        return {'job_id':job.id,'proposal_id':job.proposal_id,'state':job.state,'task':job.task,
                'expert':{k:job.profile[k] for k in ('profile','requested_label','provider','model','effort')},
                'expires_at':job.expires,'confirmed':job.confirmed,'error':job.error}

    async def start(self,proposal_id,call_id):
        async with self.lock:
            job=next((j for j in self.jobs.values() if j.proposal_id==proposal_id),None)
            if not job or job.owner!=self.session.access.effective_scope:raise ValueError('expert_proposal_not_found')
            if job.call_id:
                if job.call_id==call_id:return job
                raise ValueError('expert_job_already_started')
            if job.state!='awaiting_confirmation' or not job.confirmed or time.time()>job.expires or job.revision!=len(self.session.turns):raise PermissionError('current_user_confirmation_required')
            if any(j.state in {'queued','running'} for j in self.jobs.values()):raise PermissionError('one_active_expert_job_only')
            if not self.session.offer.expert_quota_consent:raise PermissionError('expert_quota_consent_required')
            if not getattr(self.session,'expert_authorized',False):raise PermissionError('confirmed_adult_required_for_expert')
            if not getattr(getattr(self.session,'policy',None),'expert_jobs_allowed',False):raise PermissionError('expert_not_in_session_budget')
            await asyncio.to_thread(self.budget.reserve_session,job.id,True)
            job.call_id=call_id;job.state='queued'
            job.worker=self.session.spawn(self.run(job))
            return job

    async def execute(self,job):
        s=self.session
        req=ChatRequest(text=job.task,device_id=s.access.effective_scope,conversation_id=s.access.context_conversation,
                        remember=False,turn_id=job.id,provider=job.profile['provider'],model_id=job.profile['model'],usage_consent=True)
        context=await asyncio.to_thread(s.manager.brain.memory.context,req)
        packet=await asyncio.to_thread(s.manager.brain.context_manager.pack,req.text,context,'REASONING')
        packet['expert_deliverable']='Give checkable conclusions, assumptions, source status and caveats. No hidden chain-of-thought. Tools and file access unavailable. Current facts need evidence.'
        packet['already_explained_by_gobot']=s.current.answer[:2000] if s.current else ''
        result=''
        async for delta in bridge_stream(s.manager.brain.settings,req,packet,expert_profile=job.profile['profile']):
            result+=delta
            if len(result)>24000:raise ValueError('expert_result_limit')
        job.provider_session=packet.get('_provider_session_id')
        return result

    async def run(self,job):
        s=self.session
        try:
            job.state='running';s.emit('expert_job',job=self.public(job))
            async with asyncio.timeout(90):text=await self.executor(job)
            if s.closed or job.state=='cancelled':return
            job.result=normalize_result(text,job.profile);job.state='completed'
        except asyncio.CancelledError:job.state='cancelled';raise
        except TimeoutError:job.state='timed_out';job.error='expert_timeout'
        except Exception:job.state='failed';job.error='expert_failed_no_retry'
        finally:
            if not s.closed:
                s.emit('expert_job',job=self.public(job))
                await self.return_result(job)

    async def return_result(self,job):
        s=self.session
        if job.returned or not job.call_id or s.closed:return
        job.returned=True
        current=(job.revision==len(s.turns) and job.owner==s.access.effective_scope and not s.current.cancelled)
        output={'job_id':job.id,'state':job.state}
        if current and job.result:output['result']=job.result
        else:output['result_withheld']='Context changed or task unavailable; do not invent an expert conclusion.'
        import json
        await s.send({'type':'conversation.item.create','item':{'type':'function_call_output','call_id':job.call_id,'output':json.dumps(output,ensure_ascii=False)}})
        if current and job.result:s.emit('expert_result',result=job.result)
        if current:await s.response()

    async def cancel(self,job_id):
        job=self.jobs.get(job_id)
        if not job or job.owner!=self.session.access.effective_scope:raise ValueError('expert_job_not_found')
        job.state='cancelled'
        if job.worker:job.worker.cancel();await asyncio.gather(job.worker,return_exceptions=True)
        return self.public(job)

    async def close(self):
        for job in self.jobs.values():
            if job.state in {'awaiting_confirmation','queued','running'}:
                job.state='cancelled'
                if job.worker:job.worker.cancel()
        await asyncio.gather(*(j.worker for j in self.jobs.values() if j.worker),return_exceptions=True)
