"""Delete only an explicitly enrolled local wake sample; never uploads data."""
import argparse,json,re,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
DIRECTORY=ROOT/'data/hardware/gobot-v1/wake-human'

def paths(ident):
    if not re.fullmatch('[a-f0-9]{32}',ident):raise ValueError('Invalid sample identifier')
    root=DIRECTORY.resolve();p=root/(ident+'.dpapi')
    if not root.is_relative_to(ROOT.resolve()) or p.is_symlink() or p.with_suffix('.json').is_symlink() or not p.resolve().is_relative_to(root):raise ValueError('Unsafe sample path')
    return p,p.with_suffix('.json')

def cleanup(ident,now=None):
    p,meta=paths(ident)
    if not meta.exists():return False
    data=json.loads(meta.read_text());now=time.time() if now is None else now
    if now<float(data['expires_at']):return False
    p.unlink(missing_ok=True)
    meta.write_text(json.dumps({'expires_at':data['expires_at'],'deleted_at':now,'deleted':True}))
    return True

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('sample_id');v=a.parse_args();cleanup(v.sample_id)
