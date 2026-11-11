"""Private A/B entry points, one Brain, immutable legacy browser assets."""
import hashlib,json,subprocess
from pathlib import Path
from fastapi import HTTPException
from fastapi.responses import HTMLResponse,FileResponse

BASELINE='a71b71e987efdfe01884e34de10712782c0e36ac'
ROOT=Path(__file__).resolve().parents[3]

def prepare(root=None):
    destination=Path(root or ROOT/'run/demo2')/'a'
    destination.mkdir(parents=True,exist_ok=True)
    names=subprocess.check_output(['git','ls-tree','-r','--name-only',BASELINE,'--','services/phone/dist'],cwd=ROOT,text=True).splitlines()
    files={}
    for name in names:
        relative=Path(name).relative_to('services/phone/dist').as_posix()
        data=subprocess.check_output(['git','show',BASELINE+':'+name],cwd=ROOT)
        path=destination/'assets'/relative
        if not path.resolve().is_relative_to(destination.resolve()):raise ValueError('invalid_demo_asset')
        path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        files[relative]=hashlib.sha256(data).hexdigest()
    manifest={'baseline':BASELINE,'files':files,'backend':'shared Brain, explicit legacy voice path','independent_server_snapshot':False}
    (destination/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    return manifest

def attach_demo2(app,root=None):
    location=Path(root or ROOT/'run/demo2')/'a'
    def read_manifest():
        try:return json.loads((location/'manifest.json').read_text(encoding='utf-8'))
        except (OSError,ValueError):raise HTTPException(503,'legacy_demo_snapshot_not_prepared')
    def original(asset):
        manifest=read_manifest()
        if asset not in manifest['files']:raise HTTPException(404)
        path=location/'assets'/asset
        if not path.resolve().is_relative_to((location/'assets').resolve()):raise HTTPException(404)
        data=path.read_bytes()
        if hashlib.sha256(data).hexdigest()!=manifest['files'][asset]:raise HTTPException(503,'legacy_demo_asset_changed')
        return path,data
    def page(which,device=False):
        name='device.html' if device else 'browser.html'
        if which=='a':
            _,raw=original(name);html=raw.decode('utf-8')
            for asset in read_manifest()['files']:
                html=html.replace('src="/'+asset+'"','src="/demo2/a/assets/'+asset+'"').replace('href="/'+asset+'"','href="/demo2/a/assets/'+asset+'"')
            html=html.replace('</head>','<script src="/demo2/a/compat.js"></script></head>')
        else:
            html=(ROOT/'services/phone/dist'/name).read_text(encoding='utf-8')
            html=html.replace('<body','<body data-conversation-engine="'+('live' if which=='c' else 'realtime')+'"',1)
        html=html.replace('href="/device"','href="/demo2/'+which+'/device"').replace('href="/"','href="/demo2/'+which+'"')
        html=html.replace('Браузерный прототип',('A · Legacy' if which=='a' else 'C · GPT-Live 1' if which=='c' else 'B · Realtime Mini'))
        label=('A · Legacy STT → CLI → TTS · интерфейс a71b71e · общий Brain' if which=='a' else 'C · GPT-Live 1 · 1.1 API не подтверждён' if which=='c' else 'B · Native Realtime Mini · общий Owner Full Test')
        html=html.replace('<main>','<main><p class="hint"><a href="/demo2">← Демо 2 · A/B</a> · '+label+'</p>',1)
        return HTMLResponse(html,headers={'X-GoBot-Demo-Engine':'legacy' if which=='a' else 'gpt_live' if which=='c' else 'realtime','X-GoBot-Demo-Baseline':BASELINE if which=='a' else 'candidate','Cache-Control':'no-store'})
    @app.get('/demo2')
    async def selector():return FileResponse(ROOT/'services/phone/dist/demo2.html',media_type='text/html')
    @app.get('/demo2/a')
    async def legacy():return page('a')
    @app.get('/demo2/a/device')
    async def legacy_device():return page('a',True)
    @app.get('/demo2/b')
    async def candidate():return page('b')
    @app.get('/demo2/b/device')
    async def candidate_device():return page('b',True)
    @app.get('/demo2/c')
    async def live_candidate():return page('c')
    @app.get('/demo2/c/device')
    async def live_candidate_device():return page('c',True)
    @app.get('/demo2/a/assets/{asset:path}')
    async def asset(asset:str):
        path,_=original(asset)
        mime='text/javascript' if path.suffix=='.js' else 'text/css' if path.suffix=='.css' else None
        return FileResponse(path,media_type=mime)
    @app.get('/demo2/a/compat.js')
    async def compat():return FileResponse(ROOT/'services/phone/dist/demo2-a-compat.js',media_type='text/javascript',headers={'Cache-Control':'no-store'})
