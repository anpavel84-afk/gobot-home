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

def candidate_path(ident,sha):
    p,_=paths(ident)
    if not re.fullmatch('[a-f0-9]{64}',sha):raise ValueError('Invalid private candidate hash')
    out=p.with_name(ident+'-candidate-'+sha+'.dpapi')
    if out.is_symlink():raise ValueError('Unsafe candidate path')
    return out

def cleanup(ident,now=None):
    p,meta=paths(ident)
    if not meta.exists():return False
    data=json.loads(meta.read_text());now=time.time() if now is None else now
    if now<float(data['expires_at']):return False
    p.unlink(missing_ok=True)
    derived=p.with_name(ident+'-personal-model.dpapi')
    if derived.is_symlink():raise ValueError('Unsafe derived model path')
    derived.unlink(missing_ok=True)
    for candidate in p.parent.glob(ident+'-candidate-*.dpapi'):
        match=re.fullmatch(re.escape(ident)+r'-candidate-([a-f0-9]{64})\.dpapi',candidate.name)
        if match:candidate_path(ident,match[1]).unlink(missing_ok=True)
    selection=p.with_name(ident+'-mined-public-negatives.json')
    if selection.is_symlink():raise ValueError('Unsafe private negative-selection path')
    selection.unlink(missing_ok=True)
    meta.write_text(json.dumps({'expires_at':data['expires_at'],'deleted_at':now,'deleted':True}))
    return True

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('sample_id');v=a.parse_args();cleanup(v.sample_id)
