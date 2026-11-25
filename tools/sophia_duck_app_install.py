"""Install/restore the exact Sophia wake-duck successor of verified 0.4.19.

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

PREDECESSOR_VERSION = '0.4.19-dev-sophia-touch-v4'
PREDECESSOR_SHA = '6be635649b57e31ccf625efd05ca27ae1e2551c28cf66a6a049772cb1fb4f252'
PREDECESSOR_BYTES = 3696624
PREDECESSOR_MANIFEST = ROOT/'firmware/spotpear/host/sophia_touch_v419_manifest.json'
PREDECESSOR_MANIFEST_SHA = '66bf988290d716a8d2bb0bb7497502583ecc73c165945a69adeb985dd656811c'
CANDIDATE_VERSION = '0.4.20-dev-sophia-duck-v4'


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
        core.fail('manifest_not_verified_duck_successor')
    candidate_sha = core.checked_sha(manifest.get('candidate_app_sha256'))
    candidate_size = manifest.get('candidate_app_size')
    if type(candidate_size) is not int or not 256 <= candidate_size <= core.APP_CAPACITY:
        core.fail('manifest_candidate_not_built')
    if args.current_sha == args.target_sha or {args.current_sha, args.target_sha} != {PREDECESSOR_SHA, candidate_sha}:
        core.fail('images_must_be_exact_v419_and_duck_candidate')
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
    # A physical hold is an owner action even when the device otherwise reports
    # phase=0. The successor must not reboot that mute away during install or a
    # normal restoration after a fixture failure. The original CLI stays intact.
    original_uart_status = core.uart_status

    def unmuted_uart_status(port, expected_version):
        state = original_uart_status(port, expected_version)
        if state.get('muted') != '0':
            core.fail('owner_mute_deployment_deferred')
        return state

    core.uart_status = unmuted_uart_status
    try:
        return core.perform(args, validator=validate_images,
                            recovery_direction='restore_verified_predecessor')
    finally:
        core.uart_status = original_uart_status


def parser():
    value = core.parser()
    value.description = __doc__
    value.set_defaults(manifest=ROOT/'firmware/spotpear/host/sophia_duck_v420_manifest.json')
    return value


if __name__ == '__main__':
    try:
        perform(parser().parse_args())
    except Exception as error:
        print(json.dumps({'status': 'BLOCKED_OR_FAILED', 'error_type': type(error).__name__,
            'reason': str(error) if isinstance(error, ValueError) else 'inspect_private_report',
            'automatic_retry': False}), flush=True)
        raise SystemExit(1)
