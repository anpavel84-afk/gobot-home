from pathlib import Path
import json,subprocess
root=Path(__file__).resolve().parents[1];lock=json.loads((root/'docs/dependencies.lock.json').read_text(encoding='utf-8'))
for name,sparse in [('xiaozhi-server',['main/xiaozhi-server']),('xiaozhi-firmware',['docs','main/boards/spotpear','main/protocols','main/display','main/boards/common'])]:
    item=lock[name];dest=root/'vendor'/name
    if dest.exists():
        current=subprocess.check_output(['git','-C',str(dest),'rev-parse','HEAD'],text=True).strip()
        if current!=item['sha']:raise RuntimeError('Existing checkout differs; left untouched')
        continue
    subprocess.run(['git','clone','--filter=blob:none','--sparse','--no-checkout','https://github.com/'+item['repo']+'.git',str(dest)],check=True)
    subprocess.run(['git','-C',str(dest),'sparse-checkout','set',*sparse],check=True)
    subprocess.run(['git','-C',str(dest),'checkout',item['sha']],check=True)
print('Sources match pinned SHAs')
