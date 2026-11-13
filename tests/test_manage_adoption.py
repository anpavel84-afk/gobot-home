import importlib.util,copy
from pathlib import Path
import pytest

def test_existing_manager_adopts_only_complete_verified_idle_process_set(monkeypatch):
    script=Path(__file__).parents[1]/'scripts/manage.py'
    spec=importlib.util.spec_from_file_location('manage_adoption',script);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    class Process:
        pid=123
        def cwd(self):return str(m.ROOT)
        def cmdline(self):return ['python',str(script),'worker',self.name]
        def is_running(self):return True
    processes={};manifest={'supervisor':{'pid':999,'created':1},'workers':{}}
    for i,(name,port) in enumerate(m.PORTS.items(),1):
        p=Process();p.name=name;p.pid=i;processes[i]=p;manifest['workers'][name]={'pid':i,'created':1,'port':port}
    monkeypatch.setattr(m,'identity',lambda pid,created:processes.get(pid))
    assert all(p.poll() is None for p in m.adopt_existing(manifest).values())
    bad=copy.deepcopy(manifest);bad['workers']['brain']['port']=1
    with pytest.raises(RuntimeError,match='identity'):m.adopt_existing(bad)
    bad=copy.deepcopy(manifest);bad['workers'].pop('voice')
    with pytest.raises(RuntimeError,match='complete'):m.adopt_existing(bad)
    processes[999]=Process()
    with pytest.raises(RuntimeError,match='still_running'):m.adopt_existing(manifest)
