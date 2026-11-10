"""Official CLI metadata command. No user prompt and no model generation."""
import asyncio,json,shutil,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'services/brain'))
from gobot.live_agents import GEMINI_PACKAGE,WORK,gemini_environment
from gobot.processes import native_process,failure_code
async def main():
    async with native_process([shutil.which('node'),str(GEMINI_PACKAGE/'bundle/gemini.js'),'--list-extensions'],WORK/'gemini',gemini_environment(),discard_errors=False) as process:
        out,err=await asyncio.wait_for(process.communicate(),20)
        code=failure_code((out+err).decode(errors='replace'))
        reason=code if code!='agent_execution_failed' else 'gemini_startup_failed' if process.returncode else None
    credentials=ROOT/'run/gemini-home/.gemini/oauth_creds.json'
    result={'reason':reason,'model_requests':0,'metadata_command':'--list-extensions',
            'credential_mtime_ns':credentials.stat().st_mtime_ns if credentials.exists() else None,'checked':time.time()}
    (ROOT/'run/gemini-eligibility.json').write_text(json.dumps(result,indent=2))
    (ROOT/'docs/gemini-access.json').write_text(json.dumps({k:v for k,v in result.items() if k!='credential_mtime_ns'},indent=2))
    print(json.dumps({'reason':reason,'model_requests':0}))
if __name__=='__main__':asyncio.run(main())
