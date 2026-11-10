"""Manual Google OAuth handoff to the pinned official Gemini CLI auth implementation.
No credential is returned to callers. This helper never starts a model turn.
"""
import asyncio
import re
import shutil
from urllib.parse import urlsplit
from .live_agents import ROOT, WORK, gemini_environment
from .processes import native_process

class GeminiLogin:
    def __init__(self):
        self.worker=None;self.process=None;self.url=None;self.state='idle';self.lock=asyncio.Lock()
    def status(self):
        return {'state':self.state,'authorization_url':self.url if self.state=='waiting_for_code' else None,
                'oauth_cached':(ROOT/'run/gemini-home/.gemini/oauth_creds.json').exists(),
                'model_request_made':False}
    async def start(self):
        async with self.lock:
            if self.worker and not self.worker.done():return self.status()
            self.state='starting';self.url=None
            self.worker=asyncio.create_task(self.run())
        # Initial response is quick; caller polls until official URL appears.
        return self.status()
    async def run(self):
        try:
            node=shutil.which('node')
            if not node:raise RuntimeError('not installed')
            (WORK/'gemini').mkdir(parents=True,exist_ok=True)
            async with asyncio.timeout(330):
                async with native_process([node,str(ROOT/'scripts/gemini_oauth_only.mjs')],ROOT,gemini_environment()) as process:
                    self.process=process;buffer='';last_url=None
                    while chunk:=await process.stdout.read(4096):
                        buffer=(buffer+chunk.decode('utf-8',errors='replace'))[-16384:]
                        # Only the official consent URL crosses this private HTTPS boundary.
                        # All terminal output (including a possible echoed code) is discarded.
                        for match in re.findall(r'https://accounts\.google\.com/[^\s\x1b]+',buffer):
                            url=urlsplit(match)
                            if match!=last_url and url.hostname=='accounts.google.com' and url.path in {'/o/oauth2/v2/auth','/o/oauth2/auth'}:
                                last_url=match;self.url=match;self.state='waiting_for_code'
                        if 'GOBOT_OFFICIAL_OAUTH_OK' in buffer:
                            self.state='authenticated';self.url=None;return
                        if 'GOBOT_OFFICIAL_OAUTH_FAILED' in buffer:break
                    self.state='login_failed';self.url=None
        except asyncio.CancelledError:
            self.state='cancelled';self.url=None;raise
        except Exception:
            self.state='login_failed';self.url=None
        finally:self.process=None
    async def submit(self,code):
        if self.state!='waiting_for_code' or not self.process:raise ValueError('login_not_waiting')
        if not isinstance(code,str) or not re.fullmatch(r'[A-Za-z0-9_./~-]{10,2048}',code):raise ValueError('invalid_code')
        self.state='validating';self.url=None
        self.process.stdin.write(code.encode()+b'\n');await self.process.stdin.drain()
        return self.status()
    async def close(self):
        if self.worker and not self.worker.done():
            self.worker.cancel();await asyncio.gather(self.worker,return_exceptions=True)
