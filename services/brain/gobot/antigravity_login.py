"""Official agy Google OAuth in hidden ConPTY; code is never logged or persisted."""
import asyncio,json,re,time
from urllib.parse import urlsplit
from .antigravity import ROOT,WORK,argv,environment
from .processes import WindowsJob,native_process

async def authenticated():
    async with native_process(argv(stream=False)+['models'],WORK,environment(),discard_errors=False) as process:
        try:out,err=await asyncio.wait_for(process.communicate(),20)
        except TimeoutError:return False
        return process.returncode==0 and bool(out.strip())

class AntigravityLogin:
    def __init__(self):self.worker=None;self.pty=None;self.url=None;self.state='idle';self.lock=asyncio.Lock();self.confirm=None
    def status(self):
        path=ROOT/'run/antigravity-audit.json'
        data=json.loads(path.read_text()) if path.exists() else {}
        state='authenticated' if self.state=='idle' and data.get('oauth_authenticated') else self.state
        return {'state':state,'authorization_url':self.url if self.state=='waiting_for_code' else None,
                'oauth_cached':data.get('oauth_authenticated',False),'model_request_made':False,'provider':'antigravity'}
    def mark_authenticated(self):
        path=ROOT/'run/antigravity-audit.json'
        data=json.loads(path.read_text()) if path.exists() else {}
        data['oauth_authenticated']=True;data['auth_checked']=time.time()
        path.write_text(json.dumps(data,indent=2))
        self.state='authenticated';self.url=None
    async def start(self):
        async with self.lock:
            if self.worker and not self.worker.done():return self.status()
            self.state='starting';self.url=None;self.worker=asyncio.create_task(self.run())
        return self.status()
    async def run(self):
        job=None;selected=False;buffer=''
        try:
            if await authenticated():self.mark_authenticated();return
            from winpty import PtyProcess
            self.pty=await asyncio.to_thread(PtyProcess.spawn,argv(stream=False),cwd=str(WORK),env=environment(login=True),dimensions=(40,4096))
            job=WindowsJob(self.pty.pid)
            async with asyncio.timeout(330):
                while True:
                    char=await asyncio.to_thread(self.pty.read,1)
                    if not char:raise RuntimeError('auth_terminal_eof')
                    buffer=(buffer+char)[-16384:]
                    if not selected and 'Select login method:' in buffer and 'Google OAuth' in buffer:
                        self.pty.write('\r');selected=True
                    if self.state in {'starting','waiting_for_code'}:
                        urls=re.findall(r'https://[^\s\x1b]+',buffer)
                        # Only publish after the full URL line arrives (not an incomplete prefix).
                        for value in urls:
                            if urlsplit(value).hostname=='accounts.google.com' and '\n' in buffer[buffer.find(value):]:
                                self.url=value;self.state='waiting_for_code'
                    if self.state=='authenticated':return
                    if self.state=='validating' and any(x in buffer.lower() for x in ['authentication successful','signed in successfully','sign-in successful']):
                        if await authenticated():self.mark_authenticated();return
        except asyncio.CancelledError:
            if self.state!='authenticated':self.state='cancelled'
            self.url=None;raise
        except Exception:
            if self.state!='authenticated':self.state='login_failed'
            self.url=None
        finally:
            if job:job.close()
            if self.pty:
                try:await asyncio.to_thread(self.pty.close,force=True)
                except Exception:pass
            self.pty=None
    async def submit(self,code):
        if self.state!='waiting_for_code' or not self.pty:raise ValueError('login_not_waiting')
        if not isinstance(code,str) or not re.fullmatch(r'[A-Za-z0-9_./~=-]{10,2048}',code):raise ValueError('invalid_code')
        self.state='validating';self.url=None
        await asyncio.to_thread(self.pty.write,code+'\r')
        async def confirm():
            await asyncio.sleep(2)
            if await authenticated():
                self.mark_authenticated()
                if self.worker and not self.worker.done():self.worker.cancel()
        self.confirm=asyncio.create_task(confirm())
        return self.status()
    async def close(self):
        tasks=[t for t in [self.worker,self.confirm] if t and not t.done()]
        for task in tasks:task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
