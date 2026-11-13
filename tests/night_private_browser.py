"""Manual invocation: actual private HTTPS UI, clock + existing cached clip only.
No STT/TTS/LLM/native session activation. Not part of unattended unit collection.
"""
import asyncio,base64,json,subprocess,tempfile
from pathlib import Path
import httpx
from websockets.asyncio.client import connect
from night_browser import CDP,ROOT

async def main():
    area=ROOT/'run/night-train/browser';profile=Path(tempfile.mkdtemp(prefix='gobot-private-browser-'))
    chrome=Path('C:/Users/PLAN/AppData/Local/ms-playwright/chromium-1243/chrome-win64/chrome.exe')
    with (area/'private-chromium.log').open('wb') as log:
        p=subprocess.Popen([str(chrome),'--headless=new','--no-first-run','--disable-background-networking','--disable-component-update','--disable-sync','--remote-debugging-port=0','--user-data-dir='+str(profile),'about:blank'],stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        for _ in range(100):
            if (profile/'DevToolsActivePort').exists():break
            await asyncio.sleep(.05)
        port=(profile/'DevToolsActivePort').read_text().splitlines()[0]
        async with httpx.AsyncClient(trust_env=False) as client:target=(await client.put('http://127.0.0.1:'+port+'/json/new?about:blank')).json()
        async with connect(target['webSocketDebuggerUrl'],max_size=16*1024*1024) as ws:
            c=CDP(ws);await c.call('Runtime.enable');await c.call('Page.enable');await c.call('Network.enable')
            await c.call('Emulation.setDeviceMetricsOverride',{'width':390,'height':844,'deviceScaleFactor':1,'mobile':True})
            await c.call('Page.navigate',{'url':'https://plan.tailffc57c.ts.net:18786/device-next'})
            await c.wait('window.GoBotNext?.state.ready===true')
            assert await c.js("[...document.querySelectorAll('input[type=checkbox]')].every(e=>!e.checked)")
            await c.js('window.GoBotNext.submit("Который час?")')
            assert await c.js('window.GoBotNext.state.last.approved')
            assert await c.js('document.documentElement.scrollWidth<=innerWidth')
            await c.click('details summary');await c.click('#library-load');await c.wait("document.querySelector('#library-select').options.length>0")
            await c.click('#library-play');await asyncio.sleep(3)
            errors=[e for e in c.events if e.get('method')=='Runtime.exceptionThrown'];assert not errors
            await c.js('scrollTo(0,0)')
            png=await c.call('Page.captureScreenshot',{'format':'png','captureBeyondViewport':False});(area/'private-mobile-390.png').write_bytes(base64.b64decode(png['data']))
            result={'real_private_https':True,'tls_bypass':False,'viewport':[390,844],'clock_verified':True,'library':await c.js("document.querySelector('#library-status').textContent"),'cached_audio_graph_only':True,'new_paid_calls_requested':0,'javascript_exceptions':0,'physical_audibility_verified':False}
            (area/'private-evidence.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps(result,ensure_ascii=False))
    finally:p.terminate();p.wait(10)
if __name__=='__main__':asyncio.run(main())
