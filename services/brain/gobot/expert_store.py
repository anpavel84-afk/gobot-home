"""Expert admission ledger and profile-scoped results in the existing Brain database."""
import json,time
from pydantic import Field,model_validator
from .realtime_contract import RealtimePolicy
from .realtime_budget import RealtimeBudget
from .expert_profiles import ExpertProfileName

class ExpertPolicy(RealtimePolicy):
    allowed_profiles:list[ExpertProfileName]=Field(default_factory=list,max_length=5)
    job_timeout_seconds:int=Field(default=90,ge=10,le=180)
    max_result_characters:int=Field(default=8000,ge=500,le=24000)
    max_context_tokens:int=Field(default=3000,ge=500,le=6000)
    @model_validator(mode='after')
    def bounded_expert_grant(self):
        if self.enabled and (not self.allowed_profiles or not self.allowed_client_id or not self.owner_full_test and (self.max_sessions is None or self.expires_at is None)):
            raise ValueError('Expert grant needs explicit profiles, client, expiry and finite job count')
        return self

class ExpertBudget(RealtimeBudget):
    def policy(self):
        p=ExpertPolicy.model_validate_json(self.policy_path.read_text(encoding='utf-8')) if self.policy_path.exists() else ExpertPolicy()
        if p.owner_full_test:
            from .owner_testing import OwnerTesting
            owner=OwnerTesting(self.root.parent/'owner-testing')
            p=p.model_copy(update={'enabled':owner.authorized(p.allowed_client_id) and owner.policy().experts_enabled})
        return p
    def record_cli_usage(self,job_id,usage):
        allowed={'inputTokens','outputTokens','totalTokens','cachedInputTokens','reasoningOutputTokens','input_tokens','output_tokens','total_tokens'}
        clean={k:v for k,v in usage.items() if k in allowed and type(v) is int and v>=0}
        with self.connect() as c:
            c.execute('CREATE TABLE IF NOT EXISTS cli_usage(job TEXT PRIMARY KEY,usage TEXT)')
            c.execute('INSERT OR IGNORE INTO cli_usage VALUES(?,?)',(self.key(job_id),json.dumps(clean)))

class ExpertStore:
    def __init__(self,memory,family):
        self.memory=memory;self.family=family
        with memory.connect() as c:
            c.execute('''CREATE TABLE IF NOT EXISTS expert_results(
                id TEXT PRIMARY KEY,profile_id TEXT NOT NULL REFERENCES family_profiles(id) ON DELETE CASCADE,
                profile_epoch TEXT NOT NULL,conversation_id TEXT NOT NULL,state TEXT NOT NULL,
                document TEXT NOT NULL,updated REAL NOT NULL)''')
            # A restart never restarts a paid operation with an unknown outcome.
            c.execute("UPDATE expert_results SET state='interrupted' WHERE state IN ('queued','running')")
            c.execute('INSERT OR IGNORE INTO schema_migrations VALUES(8,?)',(time.time(),))

    def save(self,job,family_epoch):
        if not job.profile_id or not job.remember:return False
        if not self.family or not self.family.session_valid(job.profile_id,family_epoch):return False
        document={'job_id':job.id,'proposal_id':job.proposal_id,'task':job.task,'expert':job.profile,
                  'result':job.result,'error':job.error,'call_id':job.call_id,'provider_session':job.provider_session,'usage':job.usage,'timings_ms':job.timings}
        with self.memory.connect() as c:
            row=c.execute('SELECT age,epoch FROM family_profiles WHERE id=?',(job.profile_id,)).fetchone()
            if not row or row['age']=='child' or row['epoch']!=family_epoch:return False
            c.execute('INSERT INTO expert_results VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET state=excluded.state,document=excluded.document,updated=excluded.updated',
                (job.id,job.profile_id,family_epoch,job.conversation,job.state,json.dumps(document,ensure_ascii=False),time.time()))
        return True

    def list(self,profile_id,epoch,conversation=None):
        if not self.family:raise PermissionError('confirmed_profile_required')
        self.family.preferences.authorize(profile_id,profile_id,epoch)
        if self.family.preferences.profile(profile_id)['age']=='child':raise PermissionError('adult_profile_required')
        with self.memory.connect() as c:
            rows=c.execute('SELECT state,document,updated FROM expert_results WHERE profile_id=? AND profile_epoch=? AND (? IS NULL OR conversation_id=?) ORDER BY updated DESC LIMIT 20',
                           (profile_id,epoch,conversation,conversation)).fetchall()
        return [{**json.loads(row['document']),'state':row['state'],'updated_at':row['updated']} for row in rows]
