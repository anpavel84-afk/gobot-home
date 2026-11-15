"""Real Chromium, production gateway/API/player, fixture DB, denied paid egress.

Run with project Python. Does not access the household Brain or open provider sessions.
"""
import asyncio,base64,json,os,socket,subprocess,sys,tempfile,threading,time
from pathlib import Path
import httpx,pytest,uvicorn
from websockets.asyncio.client import connect
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'services/brain'),str(ROOT/'tests')]
from hybrid_host import setup_host,block_paid,browser_host
REAL_CLIENT=httpx.AsyncClient

class CDP:
    def __init__(self,ws):self.ws=ws;self.serial=0;self.events=[]
    async def call(self,method,params=None):
        self.serial+=1;ident=self.serial
        await self.ws.send(json.dumps({'id':ident,'method':method,'params':params or {}}))
        while True:
            value=json.loads(await asyncio.wait_for(self.ws.recv(),30))
            if value.get('id')==ident:
                if 'error' in value:raise RuntimeError(value['error'])
                return value.get('result',{})
            self.events.append(value)
    async def js(self,expression):
        result=await self.call('Runtime.evaluate',{'expression':expression,'awaitPromise':True,'returnByValue':True,'userGesture':True})
        if result.get('exceptionDetails'):raise AssertionError(result['exceptionDetails'])
        return result.get('result',{}).get('value')
    async def wait(self,expression,seconds=12):
        start=time.monotonic()
        while time.monotonic()-start<seconds:
            if await self.js(expression):return
            await asyncio.sleep(.05)
        raise AssertionError('Browser condition timed out: '+expression+'; '+str(await self.js("document.getElementById('next-status')?.textContent")))
    async def click(self,selector):
        point=await self.js("(()=>{const e=document.querySelector("+json.dumps(selector)+");e.scrollIntoView({block:'center'});const r=e.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};})()")
        await self.call('Input.dispatchMouseEvent',{'type':'mousePressed',**point,'button':'left','clickCount':1})
        await self.call('Input.dispatchMouseEvent',{'type':'mouseReleased',**point,'button':'left','clickCount':1})

async def main():
    area=ROOT/'run/night-train/browser';area.mkdir(parents=True,exist_ok=True)
    folder=Path(tempfile.mkdtemp(prefix='gobot-next-browser-'));patch=pytest.MonkeyPatch();host=setup_host(folder)
    block_paid(patch,host);app=browser_host(patch,host)
    sock=socket.socket();sock.bind(('127.0.0.1',0));sock.listen(128);port=sock.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(app,log_level='error',access_log=False))
    thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True);thread.start()
    for _ in range(100):
        if server.started:break
        await asyncio.sleep(.05)
    assert server.started
    chrome=Path('C:/Users/PLAN/AppData/Local/ms-playwright/chromium-1243/chrome-win64/chrome.exe')
    assert chrome.exists(),'Pinned installed Chromium unavailable'
    profile=folder/'chromium';profile.mkdir()
    with (area/'chromium.log').open('wb') as log:
        process=subprocess.Popen([str(chrome),'--headless=new','--no-first-run','--no-default-browser-check',
            '--disable-background-networking','--disable-component-update','--disable-sync',
            '--remote-debugging-port=0','--user-data-dir='+str(profile),'about:blank'],stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        for _ in range(100):
            if (profile/'DevToolsActivePort').exists():break
            await asyncio.sleep(.05)
        devport=(profile/'DevToolsActivePort').read_text().splitlines()[0]
        async with REAL_CLIENT(trust_env=False) as client:
            target=(await client.put('http://127.0.0.1:'+devport+'/json/new?about:blank')).json()
        async with connect(target['webSocketDebuggerUrl'],max_size=16*1024*1024) as ws:
            cdp=CDP(ws);await cdp.call('Runtime.enable');await cdp.call('Page.enable');await cdp.call('Network.enable')
            await cdp.call('Emulation.setDeviceMetricsOverride',{'width':390,'height':844,'deviceScaleFactor':1,'mobile':True})
            await cdp.call('Page.navigate',{'url':f'http://127.0.0.1:{port}/device-next'})
            await cdp.wait('window.GoBotNext?.state.ready===true')
            assert not host['paid_calls']
            async def submit(text):return await cdp.js('window.GoBotNext.submit('+json.dumps(text,ensure_ascii=False)+')')
            await submit('Поставь таймер на три минуты')
            assert await cdp.js('window.GoBotNext.state.last.approved')
            await cdp.wait("document.querySelector('#next-timers button')?.textContent.includes('Таймер')")
            await submit('Какая сейчас погода?');await submit('А завтра?')
            assert await cdp.js("window.GoBotNext.state.last.answer.canonical_facts.days[0].date==='2026-11-14'")
            await submit('А в субботу?');await submit('Поставь таймер');await submit('Который час?');await submit('Да')
            assert await cdp.js("window.GoBotNext.state.last.route_type==='CLARIFY_SLOT'")
            await submit('Не ставь таймер, объясни, что он делает')
            with host['brain'].memory.connect() as db:assert db.execute('SELECT count(*) FROM timers').fetchone()[0]==1
            await cdp.click('#story-fixture');await cdp.wait('window.GoBotNext.state.story?.fixture===true')
            await cdp.click('#story-play');await cdp.wait("window.GoBotNext.player.state==='playing'")
            await cdp.wait('window.GoBotNext.player.snapshot().level>.001')
            await cdp.click('#story-pause');await cdp.wait("window.GoBotNext.player.state==='paused'")
            position=await cdp.js('window.GoBotNext.player.offset');assert 0<=position<=1.2
            await cdp.click('#story-play');await cdp.wait("window.GoBotNext.player.state==='playing'")
            await cdp.click('#next-stop');await cdp.wait("window.GoBotNext.player.state==='stopped'")
            await asyncio.sleep(.3);assert await cdp.js('window.GoBotNext.player.source===null')
            await cdp.click('details summary');await cdp.click('#library-load');await cdp.wait("document.getElementById('library-status').textContent.includes('проверены')")
            assert await cdp.js('document.documentElement.scrollWidth<=window.innerWidth')
            await cdp.js("window.scrollTo(0,0)")
            png=await cdp.call('Page.captureScreenshot',{'format':'png','captureBeyondViewport':False})
            (area/'mobile-390.png').write_bytes(base64.b64decode(png['data']))
            await cdp.call('Page.reload');await cdp.wait('window.GoBotNext?.state.ready===true')
            await cdp.wait("document.querySelectorAll('#next-timers button').length===1")
            errors=[e for e in cdp.events if e.get('method')=='Runtime.exceptionThrown']
            assert not errors,errors
            assert host['paid_calls']==[]
            evidence={'level':'S3 browser real code on isolated fixture HTTP/auth host','browser':str(chrome.parent.parent.name),
                'viewport':[390,844],'household_runtime_used':False,'real_web_audio_graph':True,
                'fixture_story_not_model_speech':True,'pause_offset_seconds':position,'stop_no_late_source':True,
                'restored_timer_count':1,'weather_context_verified':True,'horizontal_overflow':False,
                'paid_boundary_calls':host['paid_calls'],'exception_count':len(errors),'http_paths':sorted(set(host['http_paths'])),
                'physical_iphone_acoustics':'NOT_RUN','screenshot':'mobile-390.png'}
            (area/'evidence.json').write_text(json.dumps(evidence,indent=2),encoding='utf8');print(json.dumps(evidence,ensure_ascii=False))
    finally:
        process.terminate();process.wait(10);server.should_exit=True;thread.join(5)
        await host['live'].shutdown();await host['realtime'].shutdown();patch.undo()

if __name__=='__main__':asyncio.run(main())
