"""Official pinned agy native binary; no API key, no shell or copied OAuth files."""
import asyncio,hashlib,json
from functools import lru_cache
from pathlib import Path
from .processes import AgentError,clean_environment,native_process,failure_code
ROOT=Path(__file__).resolve().parents[3]
POLICY=ROOT/'services/agent-bridge/policies/antigravity-settings.json'
WORK=ROOT/'run/agents/antigravity'

@lru_cache(maxsize=4)
def verified(path,size,mtime,checksum):return hashlib.sha512(Path(path).read_bytes()).hexdigest()==checksum

def binary():
    lock=ROOT/'docs/antigravity.lock.json'
    if not lock.exists():return None
    metadata=json.loads(lock.read_text())
    path=(ROOT/metadata['relative_binary']).resolve()
    if not path.is_relative_to(ROOT/'run/tools/antigravity') or not path.exists():return None
    info=path.stat()
    if not verified(str(path),info.st_size,info.st_mtime_ns,metadata['sha512']):raise AgentError('antigravity_binary_changed')
    return path

def environment(*,login=False):
    env=clean_environment()
    home=ROOT/'run/antigravity-home';home.mkdir(parents=True,exist_ok=True);WORK.mkdir(parents=True,exist_ok=True)
    # Observed native environment switches, validated by the project-only auth/audit probes.
    env.update({'ANTIGRAVITY_GEMINI_DIR':str(home),'ANTIGRAVITY_APP_DATA_DIR':str(home/'app'),
                'USERPROFILE':str(home),'HOME':str(home),'APPDATA':str(home/'AppData/Roaming'),'LOCALAPPDATA':str(home/'AppData/Local'),
                'ANTIGRAVITY_EXECUTABLE_DATA_DIR':str(home/'executables'),
                'AGY_CLI_DISABLE_AUTO_UPDATE':'true','AGY_CLI_HIDE_ACCOUNT_INFO':'true',
                'AGY_CLI_HIDE_LOGO':'true','NO_COLOR':'1'})
    if login:env['ANTIGRAVITY_REMOTE_OOB_AUTH']='true'
    return env

def argv(*,stream=True,model_id=None):
    executable=binary()
    if not executable:raise AgentError('antigravity_not_installed')
    command=[str(executable),'--settings',str(POLICY),'--log-file','NUL']
    if model_id:
        if model_id not in {'gemini-3.8-flash-low','gemini-3.8-flash-medium','gemini-4-argon-medium'}:raise AgentError('unsupported_antigravity_model')
        command+=['--model',model_id]
    if stream:command+=['--input-format','stream-json','--output-format','stream-json','--disable-slash-commands','--print-timeout','90s','--sandbox']
    return command

class AntigravityEvents:
    def __init__(self):self.text='';self.completed=False;self.initialized=False;self.usage=None
    def parse(self,item):
        if self.completed:return []
        kind=item.get('event')
        if kind=='init':
            self.initialized=True
            # Broad tools may be listed but every operation remains strict/deny by policy.
            if item.get('init',{}).get('permission_mode')=='always-proceed':raise AgentError('antigravity_unsafe_permissions')
            return []
        if kind=='step_update':
            step=item.get('step_update',{})
            if step.get('step_type')!='agent_response':return []
            delta=step.get('text_delta','')
            if not isinstance(delta,str):return []
            self.text+=delta;return [delta] if delta else []
        if kind=='result':
            result=item.get('result',{})
            raw=result.get('usage',{})
            self.usage={k:v for k,v in raw.items() if k in {'input_tokens','output_tokens','thinking_tokens','cache_read_tokens','total_tokens'} and isinstance(v,int) and v>=0}
            if result.get('status')!='SUCCESS':raise AgentError(failure_code(result.get('error','')))
            final=result.get('response','')
            if not isinstance(final,str):raise AgentError('antigravity_invalid_result')
            if final.startswith(self.text):delta=final[len(self.text):]
            elif not self.text:delta=final
            else:raise AgentError('antigravity_final_mismatch')
            self.text+=delta;self.completed=True;return [delta] if delta else []
        return []

def status(consent=False):
    try:installed=binary() is not None
    except AgentError:return {'installed':True,'available':False,'reason':'antigravity_binary_changed','isolation_verified':False,'oauth_cached':False}
    path=ROOT/'run/antigravity-audit.json'
    evidence=json.loads(path.read_text()) if path.exists() else {}
    isolated=evidence.get('policy_sha256')==hashlib.sha256(POLICY.read_bytes()).hexdigest() and evidence.get('deny_verified') is True and evidence.get('adapter_sha256')==hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    auth=evidence.get('oauth_authenticated') is True
    reason='not_installed' if not installed else 'oauth_login_required' if not auth else 'isolation_not_verified' if not isolated else 'quota_consent_required' if not consent else None
    return {'installed':installed,'available':reason is None,'reason':reason,'isolation_verified':isolated,'oauth_cached':auth,'quota_consent':consent}

class AntigravityAdapter:
    def __init__(self):self.usage=None
    async def stream(self,text,context,model_id=None):
        from .live_agents import context_prompt
        parser=AntigravityEvents()
        async with native_process(argv(model_id=model_id),WORK,environment()) as process:
            process.stdin.write(json.dumps({'event':'user','message':{'content':context_prompt(text,context)}},ensure_ascii=False).encode()+b'\n')
            await process.stdin.drain()
            try:
                async with asyncio.timeout(95):
                    while line:=await process.stdout.readline():
                        try:item=json.loads(line)
                        except ValueError:continue
                        for delta in parser.parse(item):yield delta
                        if parser.completed:self.usage=parser.usage;return
                raise AgentError(process.gobot_failure or 'antigravity_incomplete_stream')
            finally:process.stdin.close()
