from pathlib import Path
import subprocess,json,shutil
r=Path.cwd();results={}
for name,args in {'codex':['codex.cmd','login','status'],'cursor':['cursor-agent.cmd','status']}.items():
 try:
  p=subprocess.run(args,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=25)
  output=(p.stdout+' '+p.stderr).lower()
  state='authenticated' if ('logged in' in output or 'authenticated' in output) and not any(x in output for x in ['not logged','not authenticated','unauthenticated']) else 'unconfirmed'
  results[name]={'exit_code':p.returncode,'state':state,'credentials_copied':False,'model_request_sent':False}
 except Exception as e:results[name]={'state':'unconfirmed','reason':type(e).__name__}
(r/'docs/auth-visibility.json').write_text(json.dumps(results,indent=2),encoding='utf-8');print(json.dumps(results,indent=2))
