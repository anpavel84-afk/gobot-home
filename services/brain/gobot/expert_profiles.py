"""Exact expert selection. Labels do not silently substitute model or effort."""
import json
from pathlib import Path

PROFILES={
    'ARGON_DEEP':{'requested_label':'Argon Deep','provider':'antigravity','model':'gemini-4-argon-medium','effort':'medium','effort_transport':'model_id_suffix','metadata_source':'authenticated Antigravity session/new model registry'},
    'ASTRA_HIGH':{'requested_label':'Astra High','provider':'codex','model':'gpt-6-astra','effort':'high','effort_transport':'model_reasoning_effort','metadata_source':'Codex model/list'},
    'SOL_XHIGH':{'requested_label':'Sol Extra High','provider':'codex','model':'gpt-6.1-sol','effort':'xhigh','effort_transport':'model_reasoning_effort','metadata_source':'Codex model/list'},
}

def resolve_profile(name,*,codex_metadata=None):
    if name not in PROFILES:raise ValueError('unknown_expert_profile')
    result={'profile':name,**PROFILES[name]}
    if result['provider']=='codex':
        path=Path.home()/'.codex/models_cache.json' # Model metadata only; never auth.json.
        try:rows=codex_metadata if codex_metadata is not None else json.loads(path.read_text(encoding='utf-8'))['models']
        except (OSError,ValueError,KeyError):rows=[]
        match=next((m for m in rows if m.get('slug',m.get('model'))==result['model']),None)
        efforts={e.get('effort',e.get('reasoningEffort')) for e in (match or {}).get('supported_reasoning_levels',(match or {}).get('supportedReasoningEfforts',[]))}
        verified=bool(match and result['effort'] in efforts)
    else:
        path=Path(__file__).resolve().parents[3]/'docs/antigravity-acp-candidate.json'
        try:
            data=json.loads(path.read_text(encoding='utf-8'))
            verified=result['model'] in json.dumps(data.get('sessions',data))
        except (OSError,ValueError):verified=False
    result.update(metadata_verified=verified,availability='metadata_confirmed' if verified else 'unavailable',
                  consent_required=True,usage_kind='cli_subscription',known_limitations=['No real quality benchmark','No filesystem, shell, web or MCP tools','Separate expert budget required'])
    return result

def profile_status():
    from .live_agents import agent_status
    statuses=agent_status(False)
    rows=[]
    for name in PROFILES:
        row=resolve_profile(name);state=statuses.get(row['provider'],{})
        row['isolation_verified']=state.get('isolation_verified',False)
        row['available_without_consent']=False
        row['admission_reason']=state.get('reason')
        rows.append(row)
    return rows
