"""Install/restore the exact Sophia admission-UI successor of verified 0.4.16.

The predecessor is pinned to the already installed, recoverable application.
The original V4 installer still accepts only its original pair. This wrapper
reuses its UART/ROM/partition checks, exclusive attempt marker and one app-only
write at 0x20000. No NVS, assets, inactive slot, provider or grant operation.
"""
from pathlib import Path
import importlib.util
import json

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('sophia_app_install_core', ROOT/'tools/sophia_v4_app_install.py')
core = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(core)

PREDECESSOR_VERSION = '0.4.16-dev-sophia-unified-v4'
PREDECESSOR_SHA = 'c6a50457a7aeec8ade964c4fb83781a6e7610ad9558343a7f72d595a40e41102'
PREDECESSOR_BYTES = 3687296
PREDECESSOR_MANIFEST = ROOT/'firmware/spotpear/host/sophia_unified_v4_manifest.json'
PREDECESSOR_MANIFEST_SHA = '3a1fcfafba4f8ef90d01a7aad28957a1ebffef8af1a36aa42f3b3d9735c9c656'
CANDIDATE_VERSION = '0.4.17-dev-sophia-ui-v4'


def validate_images(args):
    if core.sha256(PREDECESSOR_MANIFEST) != PREDECESSOR_MANIFEST_SHA:
        core.fail('verified_predecessor_manifest_changed')
    previous = json.loads(PREDECESSOR_MANIFEST.read_text(encoding='utf-8'))
    if (previous.get('candidate_version') != PREDECESSOR_VERSION or
            previous.get('candidate_app_sha256') != PREDECESSOR_SHA or
            previous.get('candidate_app_size') != PREDECESSOR_BYTES):
        core.fail('verified_predecessor_identity_changed')
    manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
    if (manifest.get('parent_manifest_sha256') != PREDECESSOR_MANIFEST_SHA or
            manifest.get('baseline_version') != PREDECESSOR_VERSION or
            manifest.get('baseline_app_sha256') != PREDECESSOR_SHA or
            manifest.get('baseline_app_size') != PREDECESSOR_BYTES or
            manifest.get('candidate_version') != CANDIDATE_VERSION or
            manifest.get('app_offset') != '0x20000' or
            manifest.get('app_slot_capacity') != core.APP_CAPACITY or
            manifest.get('model') != 'wn10_sophia' or
            manifest.get('detector_mode') != 'DET_MODE_95'):
        core.fail('manifest_not_verified_admission_successor')
    candidate_sha = core.checked_sha(manifest.get('candidate_app_sha256'))
    candidate_size = manifest.get('candidate_app_size')
    if type(candidate_size) is not int or not 256 <= candidate_size <= core.APP_CAPACITY:
        core.fail('manifest_candidate_not_built')
    if args.current_sha == args.target_sha or {args.current_sha, args.target_sha} != {PREDECESSOR_SHA, candidate_sha}:
        core.fail('images_must_be_exact_v416_and_admission_candidate')
    current = core.app_info(args.current_image, args.current_sha)
    target = core.app_info(args.target_image, args.target_sha)
    for info in (current, target):
        predecessor = info['sha256'] == PREDECESSOR_SHA
        if (info['version'] != (PREDECESSOR_VERSION if predecessor else CANDIDATE_VERSION) or
                info['bytes'] != (PREDECESSOR_BYTES if predecessor else candidate_size)):
            core.fail('app_manifest_identity_mismatch')
    if current['version'] != args.expected_current_version:
        core.fail('expected_current_version_mismatch')
    return {'current': current, 'target': target,
        'direction': 'restore_verified_predecessor' if args.target_sha == PREDECESSOR_SHA else 'install_candidate',
        'manifest_sha256': core.sha256(args.manifest),
        'parent_manifest_sha256': PREDECESSOR_MANIFEST_SHA,
        'installer_sha256': core.sha256(Path(__file__)),
        'core_installer_sha256': core.sha256(ROOT/'tools/sophia_v4_app_install.py')}


def perform(args):
    return core.perform(args, validator=validate_images,
                        recovery_direction='restore_verified_predecessor')


def parser():
    value = core.parser()
    value.description = __doc__
    value.set_defaults(manifest=ROOT/'firmware/spotpear/host/sophia_admission_v417_manifest.json')
    return value


if __name__ == '__main__':
    try:
        perform(parser().parse_args())
    except Exception as error:
        print(json.dumps({'status': 'BLOCKED_OR_FAILED', 'error_type': type(error).__name__,
            'reason': str(error) if isinstance(error, ValueError) else 'inspect_private_report',
            'automatic_retry': False}), flush=True)
        raise SystemExit(1)
