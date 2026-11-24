"""Install or restore only the approved exact Sophia v420/v421 application pair.

The unchanged V4 core retains UART/ROM checks, partition and OTA verification,
private reports, the durable one-write marker and app-only address 0x20000.
This validator independently pins both images, the source/build provenance and
the core before importing it. A changed manifest cannot authorize another bin.
The original source manifest stays source-only; build evidence is a separate
install manifest. Ordinary forward and reverse operations preserve owner Mute.

--files-only uses no hardware. Actual execution also requires an external idle,
owned-Gateway maintenance and fresh board identity/security/backup preflight;
this low-level installer does not claim those orchestration checks. No NVS,
inactive slot, assets, grants, model calls or automatic retry are supported.
"""
from pathlib import Path
import hashlib
import importlib.util
import json


ROOT = Path(__file__).resolve().parents[1]
CORE_PATH = ROOT/'tools/sophia_v4_app_install.py'
CORE_SHA = 'a0e6c9509d6d6d14b62f66de150c9e2adb44ba4695c071f99d984c1fb1d89a32'
PREDECESSOR_VERSION = '0.4.20-dev-sophia-duck-v4'
PREDECESSOR_SHA = '11956a9e4700c6c53f49ba03c3f3f12daae208d010c319305b2a9d704d52388e'
PREDECESSOR_BYTES = 3700240
PREDECESSOR_MANIFEST = ROOT/'firmware/spotpear/host/sophia_duck_v420_manifest.json'
PREDECESSOR_MANIFEST_SHA = '3fc70ee8e6a21f0f97f43769fe43c4d3a081dcf2e85fa1c6a6c2db797b513b35'
SOURCE_MANIFEST = ROOT/'firmware/spotpear/host/sophia_timer_v421_manifest.json'
SOURCE_MANIFEST_SHA = 'de34839fe352bf32d1669560261079f22be2236ff2c660c8e74510b8497a27f5'
INSTALL_MANIFEST = ROOT/'firmware/spotpear/host/sophia_timer_v421_install_manifest.json'
INSTALL_MANIFEST_SHA = '33cbbc90b4e2f4b672e85a8093d5d2b780fddc2e749fbc9439dfc1ff760ac8ea'
BUILD_REPORT_SHA = '630cb21df8108f5a0f7ec8199a1ec994dad4a15f89fc0c4f147479aa3da6d6e5'
CANDIDATE_VERSION = '0.4.21-dev-sophia-timer-v4'
CANDIDATE_SHA = '2e0898e708728973561f3920ddcbebc3c744a488bbf8cac95c72b62891edd68b'
CANDIDATE_BYTES = 3701840


def checked_bytes(path, expected, reason):
    path = Path(path)
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 131072:
        raise ValueError(reason)
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError(reason)
    return raw


# Verify before execution, including when a caller only imports this wrapper.
# Execute the exact bytes just hashed; importing from the path again would open
# a second version of the file if it were replaced between the two reads.
_core_source = checked_bytes(CORE_PATH, CORE_SHA, 'core_installer_integrity_failed')
_spec = importlib.util.spec_from_file_location('sophia_timer_install_core', CORE_PATH)
core = importlib.util.module_from_spec(_spec)
exec(compile(_core_source, str(CORE_PATH), 'exec'), core.__dict__)
del _core_source


def install_contract():
    return {
        'schema': 'sophia-timer-v421-install-v1',
        'source_manifest_sha256': SOURCE_MANIFEST_SHA,
        'parent_manifest_sha256': PREDECESSOR_MANIFEST_SHA,
        'core_installer_sha256': CORE_SHA,
        'build_report_sha256': BUILD_REPORT_SHA,
        'baseline_version': PREDECESSOR_VERSION,
        'baseline_app_sha256': PREDECESSOR_SHA,
        'baseline_app_size': PREDECESSOR_BYTES,
        'candidate_version': CANDIDATE_VERSION,
        'candidate_app_sha256': CANDIDATE_SHA,
        'candidate_app_size': CANDIDATE_BYTES,
        'app_offset': '0x20000',
        'app_slot_capacity': 0x3f0000,
        'model': 'wn10_sophia',
        'detector_mode': 'DET_MODE_95',
        'non_app_write_allowed': False,
        'automatic_retry': False,
        'physical_acceptance': False,
    }


def validate_images(args):
    checked_bytes(CORE_PATH, CORE_SHA, 'core_installer_integrity_failed')
    previous = json.loads(checked_bytes(PREDECESSOR_MANIFEST,
        PREDECESSOR_MANIFEST_SHA, 'verified_predecessor_manifest_changed'))
    source = json.loads(checked_bytes(SOURCE_MANIFEST,
        SOURCE_MANIFEST_SHA, 'verified_source_manifest_changed'))
    manifest = json.loads(checked_bytes(args.manifest,
        INSTALL_MANIFEST_SHA, 'verified_install_manifest_changed'))
    if manifest != install_contract():
        core.fail('manifest_not_exact_approved_timer_image')
    if (previous.get('candidate_version') != PREDECESSOR_VERSION or
            previous.get('candidate_app_sha256') != PREDECESSOR_SHA or
            previous.get('candidate_app_size') != PREDECESSOR_BYTES):
        core.fail('verified_predecessor_identity_changed')
    source_fields = ('baseline_version', 'baseline_app_sha256', 'baseline_app_size',
                     'candidate_version', 'parent_manifest_sha256', 'app_offset',
                     'app_slot_capacity', 'model', 'detector_mode')
    if any(source.get(key) != manifest[key] for key in source_fields):
        core.fail('verified_source_lineage_changed')
    if (args.current_sha == args.target_sha or
            {args.current_sha, args.target_sha} != {PREDECESSOR_SHA, CANDIDATE_SHA}):
        core.fail('images_must_be_exact_v420_and_approved_v421')
    current = core.app_info(args.current_image, args.current_sha)
    target = core.app_info(args.target_image, args.target_sha)
    for info in (current, target):
        predecessor = info['sha256'] == PREDECESSOR_SHA
        if (info['version'] != (PREDECESSOR_VERSION if predecessor else CANDIDATE_VERSION) or
                info['bytes'] != (PREDECESSOR_BYTES if predecessor else CANDIDATE_BYTES)):
            core.fail('app_manifest_identity_mismatch')
    if current['version'] != args.expected_current_version:
        core.fail('expected_current_version_mismatch')
    return {
        'current': current, 'target': target,
        'direction': 'restore_verified_predecessor' if args.target_sha == PREDECESSOR_SHA else 'install_candidate',
        'manifest_sha256': INSTALL_MANIFEST_SHA,
        'source_manifest_sha256': SOURCE_MANIFEST_SHA,
        'parent_manifest_sha256': PREDECESSOR_MANIFEST_SHA,
        'build_report_sha256': BUILD_REPORT_SHA,
        'installer_sha256': core.sha256(Path(__file__)),
        'core_installer_sha256': CORE_SHA,
        'board_identity_security_checked_by_installer': False,
        'factory_backups_checked_by_installer': False,
    }


def perform(args):
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
    value.set_defaults(manifest=INSTALL_MANIFEST)
    return value


if __name__ == '__main__':
    try:
        perform(parser().parse_args())
    except Exception as error:
        print(json.dumps({'status': 'BLOCKED_OR_FAILED', 'error_type': type(error).__name__,
            'reason': str(error) if isinstance(error, ValueError) else 'inspect_private_report',
            'automatic_retry': False}), flush=True)
        raise SystemExit(1)
