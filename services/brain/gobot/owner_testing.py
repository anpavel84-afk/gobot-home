"""Bound owner-device economic admission over the existing Brain and ledgers.

This grants public test operations, never a person's private memory or shell.
The model cannot edit it. All writes come from the authenticated owner settings UI.
"""
import hashlib,json,os,sqlite3,time,threading
from pathlib import Path
from pydantic import BaseModel,ConfigDict,Field
from .realtime_contract import RealtimeModel,AudioPreset

class OwnerTestPolicy(BaseModel):
    model_config=ConfigDict(extra='forbid')
    enabled:bool=False
    authorization:str=Field(default='',max_length=200)
    allowed_client_id:str=Field(default='',max_length=100)
    api_estimate_usd_per_day:float=Field(default=10,ge=1,le=500,allow_inf_nan=False)
    realtime_responses_per_day:int=Field(default=500,ge=10,le=10000)
    expert_jobs_per_day:int=Field(default=20,ge=1,le=100)
    image_attempts_per_day:int=Field(default=20,ge=1,le=100)
    experts_enabled:bool=True
    images_enabled:bool=True
    device_settings_enabled:bool=True
    realtime_model:RealtimeModel='gpt-realtime-2.1-mini'
    audio_preset:AudioPreset='baseline'
    revision:int=Field(default=1,ge=1)
    developer_acceptance_expires_at:float=Field(default=0,ge=0,allow_inf_nan=False)
    developer_realtime_limit:int=Field(default=0,ge=0,le=24)
    developer_expert_limit:int=Field(default=0,ge=0,le=3)
    developer_image_limit:int=Field(default=0,ge=0,le=1)
    developer_transcription_limit:int=Field(default=0,ge=0,le=2)
    live_enabled:bool=False
    live_minutes_per_day:int=Field(default=60,ge=1,le=1440)
    live_session_seconds:int=Field(default=600,ge=30,le=3600)
    developer_live_limit:int=Field(default=0,ge=0,le=5)
    developer_live_seconds:int=Field(default=0,ge=0,le=360)
    developer_live_session_seconds:int=Field(default=90,ge=15,le=90)
    developer_estimate_usd_limit:float|None=Field(default=None,ge=0,le=10,allow_inf_nan=False)
    live_backend_enabled:bool=False
    live_backend_requests_per_day:int=Field(default=500,ge=1,le=10000)
    developer_live_backend_limit:int=Field(default=0,ge=0,le=14)

class OwnerTesting:
    def __init__(self,root):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        self.policy_path=self.root/'policy.json';self.path=self.root/'usage.sqlite'
        self.lock=threading.RLock()
        with self.connect() as c:
            c.execute('CREATE TABLE IF NOT EXISTS attempts(id TEXT PRIMARY KEY,day INTEGER,kind TEXT,cost REAL,pending INTEGER)')
            if 'origin' not in {r[1] for r in c.execute('PRAGMA table_info(attempts)')}:c.execute("ALTER TABLE attempts ADD COLUMN origin TEXT NOT NULL DEFAULT 'owner'")
    def connect(self):return sqlite3.connect(self.path,timeout=5)
    def policy(self):
        return OwnerTestPolicy.model_validate_json(self.policy_path.read_text(encoding='utf-8')) if self.policy_path.exists() else OwnerTestPolicy()
    def authorized(self,binding):
        p=self.policy();return bool(p.enabled and p.authorization and binding and p.allowed_client_id==binding)
    def bound(self,binding):
        p=self.policy();return bool(p.authorization and binding and p.allowed_client_id==binding)
    def update(self,binding,patch):
        if not self.bound(binding):raise PermissionError('owner_device_required')
        if set(patch)-{'enabled','api_estimate_usd_per_day','realtime_responses_per_day','expert_jobs_per_day','image_attempts_per_day','experts_enabled','images_enabled','device_settings_enabled','realtime_model','audio_preset','live_enabled','live_minutes_per_day','live_session_seconds','live_backend_enabled','live_backend_requests_per_day'}:raise ValueError('owner_policy_field_denied')
        with self.lock:
            p=self.policy();value=OwnerTestPolicy.model_validate({**p.model_dump(),**patch,'revision':p.revision+1})
            temp=self.policy_path.with_suffix('.tmp');temp.write_text(value.model_dump_json(indent=2),encoding='utf-8');os.replace(temp,self.policy_path)
        return self.status(binding)
    def reserve(self,binding,kind,ident,*,estimate=0,origin='owner'):
        if not self.authorized(binding):raise PermissionError('owner_test_not_authorized')
        p=self.policy();caps={'realtime':p.realtime_responses_per_day,'expert':p.expert_jobs_per_day,'image':p.image_attempts_per_day,'transcription':2,'live':240,'live_backend':p.live_backend_requests_per_day}
        if kind not in caps:raise ValueError('invalid_owner_operation')
        if kind=='expert' and not p.experts_enabled:raise PermissionError('native_experts_disabled')
        if kind=='image' and not p.images_enabled:raise PermissionError('image_generation_policy_denied')
        if kind=='live_backend' and not p.live_backend_enabled:raise PermissionError('live_backend_disabled')
        key=hashlib.sha256((str(time.time()//86400)+':'+kind+':'+ident).encode()).hexdigest();day=int(time.time()//86400)
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            if c.execute('SELECT 1 FROM attempts WHERE id=?',(key,)).fetchone():return key
            if origin=='developer':
                if time.time()>p.developer_acceptance_expires_at:raise PermissionError('developer_acceptance_expired')
                count=c.execute("SELECT count(*) FROM attempts WHERE kind=? AND origin='developer'",(kind,)).fetchone()[0]
                if count>=getattr(p,'developer_'+kind+'_limit'):raise PermissionError('developer_acceptance_limit')
                spent_dev=c.execute("SELECT coalesce(sum(cost),0) FROM attempts WHERE origin='developer'").fetchone()[0]
                if p.developer_estimate_usd_limit is not None and spent_dev+estimate>p.developer_estimate_usd_limit:raise PermissionError('developer_estimate_limit')
            elif origin!='owner' or kind=='transcription':raise PermissionError('developer_acceptance_required')
            count=c.execute('SELECT count(*) FROM attempts WHERE day=? AND kind=?',(day,kind)).fetchone()[0]
            spent=c.execute('SELECT coalesce(sum(cost),0) FROM attempts WHERE day=?',(day,)).fetchone()[0]
            if count>=caps[kind]:raise PermissionError('owner_'+kind+'_daily_limit')
            if estimate and spent+estimate>p.api_estimate_usd_per_day:raise PermissionError('owner_api_estimate_limit')
            c.execute('INSERT INTO attempts VALUES(?,?,?,?,?,?)',(key,day,kind,estimate,int(estimate>0),origin))
        return key
    def settle(self,key,cost):
        if not isinstance(cost,(int,float)) or cost<0:raise ValueError('invalid_estimated_cost')
        with self.connect() as c:c.execute('UPDATE attempts SET cost=?,pending=0 WHERE id=? AND pending=1',(cost,key))
    def status(self,binding):
        p=self.policy();authorized=self.bound(binding)
        if not authorized:return {'authorized':False,'enabled':False,'reason':'owner_device_required'}
        with self.connect() as c:
            counts=dict(c.execute('SELECT kind,count(*) FROM attempts WHERE day=? GROUP BY kind',(int(time.time()//86400),)))
            cost,pending=c.execute('SELECT coalesce(sum(cost),0),coalesce(sum(pending),0) FROM attempts WHERE day=?',(int(time.time()//86400),)).fetchone()
            origins={origin:count for origin,count in c.execute('SELECT origin,count(*) FROM attempts WHERE day=? GROUP BY origin',(int(time.time()//86400),))}
        safe=p.model_dump(exclude={'authorization','allowed_client_id'})
        from .skill_catalogue import summary
        return {'authorized':True,'enabled':p.enabled,'policy':safe,'attempts_today':counts,'skill_catalogue':summary(),
                'estimated_usd_including_pending_reserves':round(cost,6),'pending_usage':pending,
                'owner_vs_developer_attempts_today':origins,
                'hard_dollar_cap_guaranteed':False,'provider_invoice':False,
                'transcription_billed_separately':True,'cli_quota_is_not_api_usd':True,
                'private_memory_authorized_by_this_mode':False,'raw_audio_saved':False}
