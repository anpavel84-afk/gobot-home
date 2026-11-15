"""Correct the golden baseline only; preserve native kernels and model bytes."""
import argparse,hashlib,json,shutil
from pathlib import Path
from prepare_product import change


def prepare(root,fixture):
    main=root/'main';meta=json.loads((fixture/'fixture.json').read_text())
    if '0.4.10-dev-native-parity-1' not in (root/'CMakeLists.txt').read_text():raise ValueError('Expected unchanged-kernel parity copy')
    cfg=(main/'gobot_mww_config.h').read_text()
    if '#define GOBOT_WAKE_ROUTE 0' not in cfg or '#define GOBOT_WAKE_OWNER_TEST 0' not in cfg:raise ValueError('Local-only diagnostic required')
    if not meta.get('synthetic_only') or meta.get('kernel_baseline')!='native_reference' or meta.get('invocations')!=1625:
        raise ValueError('Require the public reference baseline')
    if meta['model_sha256']!='4ffc532e16b3e20b7ce09099338023b5af304a0e31bf537034bb03dd67a4c5f9':raise ValueError('Model changed')
    header=fixture/'gobot_mww_fixture.h'
    if hashlib.sha256(header.read_bytes()).hexdigest()!=meta['header_sha256']:raise ValueError('Fixture changed')
    if hashlib.sha256((main/header.name).read_bytes()).hexdigest()!='150fe6270e5a723b8960a257fe0ed0f079da1aa99659ad307b342e7671cb2e91':
        raise ValueError('Expected prior desktop-optimized fixture')
    shutil.copy2(header,main/header.name)
    for p in (root/'CMakeLists.txt',main/'gobot_build_info.h'):change(p,'0.4.10-dev-native-parity-1','0.4.11-dev-ref-parity-1')
    (root/'native-reference-fixture.json').write_text(json.dumps(meta,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('isolated_copy',type=Path);p.add_argument('fixture',type=Path)
    a=p.parse_args();prepare(a.isolated_copy,a.fixture)
