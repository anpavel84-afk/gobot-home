"""Explicitly metadata-only ACP probe. Never sends session/prompt or reads auth files."""
import asyncio,hashlib,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'services/brain'))
from gobot.antigravity_acp import AcpRuntime
from gobot.antigravity import binary,POLICY

async def main():
    runtime=AcpRuntime();rows=[];started=time.perf_counter();failure=None
    try:
        await runtime.open();initialize_ms=round((time.perf_counter()-started)*1000,2)
        for _ in range(2):
            begin=time.perf_counter();session=await runtime.new_session()
            rows.append({'new_session_ms':round((time.perf_counter()-begin)*1000,2),
                'response_keys':sorted(session),'mcp_servers_requested':0,
                'advertised_models':[r.get('modelId') for r in session.get('models',{}).get('availableModels',[])],
                'current_mode':session.get('modes',{}).get('currentModeId'),
                'meta_keys':sorted(session.get('_meta',{}))})
            await runtime.end_session()
        close_supported='close' in runtime.capabilities.get('sessionCapabilities',{})
    except Exception as error:
        initialize_ms=None;close_supported=None;failure=getattr(error,'code',type(error).__name__)
    finally:await runtime.close()
    report={'binary_sha256':hashlib.sha256(binary().read_bytes()).hexdigest(),
        'policy_sha256':hashlib.sha256(POLICY.read_bytes()).hexdigest(),
        'adapter_sha256':hashlib.sha256((ROOT/'services/brain/gobot/antigravity_acp.py').read_bytes()).hexdigest(),
        'native_session_deny_verified':False,'no_permission_bypass':True,'adversarial_tool_execution_checked':False,
        'initialize_ms':initialize_ms,'session_metadata':rows,'close_advertised':close_supported,
        'failure_code':failure,'model_requests':0,'paid_api_requests':0,'prompt_sent':False,
        'runtime_terminated':runtime.cm is None,'production_enabled':False,
        'blocker':'ACP session/new does not provide effective native deny-rule proof. Client refusal of permission/FS/terminal requests cannot prove that internal agent tools are denied in session workers. No adversarial native tool test has been authorized/performed.',
        'sources':['https://antigravity.google/docs/cli/acp','https://agentclientprotocol.com/protocol/v1/session-setup','https://agentclientprotocol.com/protocol/v1/prompt-turn']}
    for path in [ROOT/'run/antigravity-acp-audit.json',ROOT/'docs/antigravity-acp-candidate.json']:
        path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':asyncio.run(main())
