"""Host-only launcher. All files and processes are scoped to this repository."""
import argparse,asyncio,json,os,secrets,socket,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];os.chdir(ROOT);sys.path.insert(0,str(ROOT/'services/brain'))
RUN=ROOT/'run';PY=ROOT/'.venv/Scripts/python.exe' if os.name=='nt' else ROOT/'.venv/bin/python'
PORTS={'brain':18781,'bridge':18782,'voice':18783,'images':18784}
def init():
    RUN.mkdir(exist_ok=True);(ROOT/'data').mkdir(exist_ok=True)
    path=RUN/'keys.json'
    if not path.exists():
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as f:json.dump({k:secrets.token_urlsafe(48) for k in ['api_token','bridge_secret','device_token','device_secret']},f)
    return json.loads(path.read_text())
def environment():
    env=os.environ.copy();env['PYTHONPATH']=str(ROOT/'services/brain');env['PYTHONUNBUFFERED']='1';env['PYTHONUTF8']='1';return env
def identity(pid,created):
    import psutil
    try:
        p=psutil.Process(pid)
        return p if abs(p.create_time()-created)<0.1 and str(ROOT).lower() in p.cwd().lower() else None
    except (psutil.NoSuchProcess,psutil.AccessDenied):return None
def spawn(command,label):
    options={'creationflags':0x08000000} if os.name=='nt' else {'start_new_session':True}
    with open(RUN/(label+'.log'),'ab') as log:
        return subprocess.Popen(command,cwd=ROOT,env=environment(),stdin=subprocess.DEVNULL,stdout=log,stderr=log,**options)
def worker(name):
    import uvicorn
    if name=='voice':
        from gobot.config import load
        from gobot.voice_mock import VoiceMock
        asyncio.run(VoiceMock(load(),init()['device_token']).serve(PORTS[name]));return
    factory={'brain':'gobot.brain:create_app','bridge':'gobot.bridge:create_app','images':'gobot.voice_mock:image_app'}[name]
    uvicorn.run(factory,factory=True,host='127.0.0.1',port=PORTS[name],access_log=False,log_level='warning',server_header=False)
def supervise():
    import psutil
    init();children={};attempts={name:0 for name in PORTS};stopping=RUN/'stop.request';stopping.unlink(missing_ok=True)
    def save():
        data={'supervisor':{'pid':os.getpid(),'created':psutil.Process().create_time()},'workers':{n:{'pid':p.pid,'created':psutil.Process(p.pid).create_time(),'port':PORTS[n]} for n,p in children.items() if p.poll() is None}}
        temp=RUN/'processes.tmp';temp.write_text(json.dumps(data,indent=2));temp.replace(RUN/'processes.json')
    try:
        while not stopping.exists():
            for name in PORTS:
                if name not in children or children[name].poll() is not None:
                    if attempts[name]>=4:raise RuntimeError('Worker restart budget exhausted: '+name)
                    with socket.socket() as s:s.bind(('127.0.0.1',PORTS[name]))
                    children[name]=spawn([str(PY),str(ROOT/'scripts/manage.py'),'worker',name],name);attempts[name]+=1
            save();time.sleep(1)
    finally:
        for p in children.values():
            if p.poll() is None:
                try:
                    owned=psutil.Process(p.pid).children(recursive=True)
                    for child in reversed(owned):
                        try:child.terminate()
                        except psutil.NoSuchProcess:pass
                    p.terminate()
                except (psutil.NoSuchProcess,ProcessLookupError):pass
        for p in children.values():
            try:p.wait(timeout=5)
            except subprocess.TimeoutExpired:p.kill();p.wait()
        (RUN/'processes.json').unlink(missing_ok=True);stopping.unlink(missing_ok=True)
def start():
    init()
    if (RUN/'processes.json').exists():
        manifest=json.loads((RUN/'processes.json').read_text());s=manifest['supervisor']
        if identity(s['pid'],s['created']):print('GoBot supervisor already running');return
    for port in PORTS.values():
        with socket.socket() as s:s.bind(('127.0.0.1',port))
    p=spawn([str(PY),str(ROOT/'scripts/manage.py'),'supervise'],'supervisor')
    import urllib.request
    for _ in range(100):
        try:
            for port in [18781,18782,18783,18784]:urllib.request.urlopen(f'http://127.0.0.1:{port}/healthz',timeout=.5).close()
            print('GoBot mock stack ready on loopback 18781-18784; supervisor PID',p.pid);return
        except (OSError,ValueError):time.sleep(.2)
    raise RuntimeError('Startup failed; see run/*.log')
def stop():
    manifest=RUN/'processes.json'
    if not manifest.exists():print('GoBot is stopped');return
    data=json.loads(manifest.read_text());supervisor=data['supervisor']
    if not identity(supervisor['pid'],supervisor['created']):raise RuntimeError('Process identity mismatch; no process touched')
    (RUN/'stop.request').write_text('owner requested stop')
    for _ in range(80):
        if not manifest.exists():print('GoBot stopped');return
        time.sleep(.1)
    raise RuntimeError('Graceful stop pending; inspect supervisor log')
def main():
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=['init','start','stop','status','supervise','worker']);parser.add_argument('name',nargs='?');args=parser.parse_args()
    if args.command=='worker':worker(args.name)
    elif args.command=='supervise':supervise()
    elif args.command=='status':print((RUN/'processes.json').read_text() if (RUN/'processes.json').exists() else 'stopped')
    elif args.command=='init':init();print('Local keys initialized; values not printed')
    elif args.command=='start':start()
    elif args.command=='stop':stop()
if __name__=='__main__':main()
