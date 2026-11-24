"""Exact timer image authorization and recovery gates; no device or provider."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_sophia_v4_app_install import app_bytes, digest, metadata


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('sophia_timer_installer',
    ROOT/'tools/sophia_timer_app_install.py')
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)


def save(path, value):
    path.write_text(json.dumps(value), encoding='utf-8')
    return digest(path.read_bytes())


@pytest.fixture
def images(tmp_path, monkeypatch):
    current, target = tmp_path/'v420.bin', tmp_path/'v421.bin'
    current.write_bytes(app_bytes(installer.PREDECESSOR_VERSION))
    target.write_bytes(app_bytes(installer.CANDIDATE_VERSION, size=768))
    # Fixtures replace only in-memory constants; production pins stay on disk.
    monkeypatch.setattr(installer, 'PREDECESSOR_SHA', digest(current.read_bytes()))
    monkeypatch.setattr(installer, 'PREDECESSOR_BYTES', current.stat().st_size)
    monkeypatch.setattr(installer, 'CANDIDATE_SHA', digest(target.read_bytes()))
    monkeypatch.setattr(installer, 'CANDIDATE_BYTES', target.stat().st_size)
    private_core = tmp_path/'core.py'
    private_core.write_bytes(installer.CORE_PATH.read_bytes())
    monkeypatch.setattr(installer, 'CORE_PATH', private_core)
    previous = tmp_path/'v420.json'
    previous_sha = save(previous, {
        'candidate_version': installer.PREDECESSOR_VERSION,
        'candidate_app_sha256': installer.PREDECESSOR_SHA,
        'candidate_app_size': installer.PREDECESSOR_BYTES,
    })
    monkeypatch.setattr(installer, 'PREDECESSOR_MANIFEST', previous)
    monkeypatch.setattr(installer, 'PREDECESSOR_MANIFEST_SHA', previous_sha)
    source = tmp_path/'source.json'
    source_sha = save(source, {
        'baseline_version': installer.PREDECESSOR_VERSION,
        'baseline_app_sha256': installer.PREDECESSOR_SHA,
        'baseline_app_size': installer.PREDECESSOR_BYTES,
        'candidate_version': installer.CANDIDATE_VERSION,
        'parent_manifest_sha256': previous_sha,
        'app_offset': '0x20000', 'app_slot_capacity': 0x3f0000,
        'model': 'wn10_sophia', 'detector_mode': 'DET_MODE_95',
    })
    monkeypatch.setattr(installer, 'SOURCE_MANIFEST', source)
    monkeypatch.setattr(installer, 'SOURCE_MANIFEST_SHA', source_sha)
    manifest = tmp_path/'install.json'
    monkeypatch.setattr(installer, 'INSTALL_MANIFEST', manifest)
    monkeypatch.setattr(installer, 'INSTALL_MANIFEST_SHA', save(manifest, installer.install_contract()))
    return SimpleNamespace(current_image=current, target_image=target,
        current_sha=installer.PREDECESSOR_SHA, target_sha=installer.CANDIDATE_SHA,
        expected_current_version=installer.PREDECESSOR_VERSION,
        manifest=manifest, report_dir=tmp_path/'private', port='COM3',
        attempt_id='timer-first', files_only=False, execute=False,
        recover_known_boot_failure=False)


def reverse(images):
    images.current_image, images.target_image = images.target_image, images.current_image
    images.current_sha, images.target_sha = images.target_sha, images.current_sha
    images.expected_current_version = installer.CANDIDATE_VERSION
    images.attempt_id = 'timer-restore'


@pytest.fixture
def simulated_device(images, monkeypatch):
    core = installer.core
    partition, ota = metadata()
    original_audit = core.audit_metadata
    monkeypatch.setattr(core, 'audit_metadata', lambda p, o: original_audit(p, o,
        partition_sha=digest(partition), ota_sha=digest(ota)))
    events = []

    def uart(port, version):
        events.append(('uart', version))
        return {'version': version, 'wifi': '1', 'enrolled': '1',
                'muted': '0', 'phase': '0', 'upload': '1'}

    def esptool(port, operation, run_dir, stage, *, image=None, region=None):
        assert port == 'COM3'
        events.append((operation, stage))
        if operation == 'read':
            assert region in {'partition', 'ota'}
            image.write_bytes(partition if region == 'partition' else ota)
        elif operation == 'write':
            report = json.loads((run_dir/'report.json').read_text())
            assert report['restore_image_matches_active_flash'] is True
            assert ('verify', 'verify-current-app') in events
            marker = json.loads(next(images.report_dir.glob('attempt-*.json')).read_text())
            assert marker['state'] == 'write_started'
            assert marker['target_sha256'] == images.target_sha
            assert core.sha256(image) == images.target_sha

    monkeypatch.setattr(core, 'uart_status', uart)
    monkeypatch.setattr(core, 'run_esptool', esptool)
    return events, esptool


def test_production_install_manifest_matches_pinned_build_and_unmodified_sources():
    assert json.loads(installer.checked_bytes(installer.INSTALL_MANIFEST,
        installer.INSTALL_MANIFEST_SHA, 'bad_install')) == installer.install_contract()
    source = json.loads(installer.checked_bytes(installer.SOURCE_MANIFEST,
        installer.SOURCE_MANIFEST_SHA, 'bad_source'))
    previous = json.loads(installer.checked_bytes(installer.PREDECESSOR_MANIFEST,
        installer.PREDECESSOR_MANIFEST_SHA, 'bad_parent'))
    assert source['baseline_app_sha256'] == previous['candidate_app_sha256'] == installer.PREDECESSOR_SHA
    assert source.get('candidate_app_sha256') is None
    assert installer.core.APP_OFFSET == 0x20000 and installer.core.APP_CAPACITY == 0x3f0000


def test_changed_core_is_rejected_before_import_execution(tmp_path):
    tools = tmp_path/'tools'
    tools.mkdir()
    wrapper = tools/'sophia_timer_app_install.py'
    wrapper.write_bytes((ROOT/'tools/sophia_timer_app_install.py').read_bytes())
    marker = tmp_path/'untrusted-code-ran'
    (tools/'sophia_v4_app_install.py').write_text(
        'from pathlib import Path\nPath('+repr(str(marker))+').write_text("unsafe")\n')
    spec = importlib.util.spec_from_file_location('timer_tampered_import', wrapper)
    module = importlib.util.module_from_spec(spec)
    with pytest.raises(ValueError, match='core_installer_integrity_failed'):
        spec.loader.exec_module(module)
    assert not marker.exists()


@pytest.mark.parametrize('attribute,reason', [
    ('CORE_PATH', 'core_installer_integrity_failed'),
    ('PREDECESSOR_MANIFEST', 'verified_predecessor_manifest_changed'),
    ('SOURCE_MANIFEST', 'verified_source_manifest_changed'),
    ('INSTALL_MANIFEST', 'verified_install_manifest_changed'),
])
def test_tampered_trust_chain_fails_before_hardware(images, monkeypatch, attribute, reason):
    getattr(installer, attribute).write_text('{}')
    monkeypatch.setattr(installer.core, 'uart_status', lambda *args:
                        pytest.fail('tampered provenance reached UART'))
    images.execute = True
    with pytest.raises(ValueError, match=reason):
        installer.perform(images)
    assert not images.report_dir.exists()


@pytest.mark.parametrize('field,value', [
    ('candidate_app_sha256', 'f'*64), ('candidate_app_size', 7680),
    ('candidate_version', 'unreviewed'), ('baseline_app_sha256', 'a'*64),
    ('build_report_sha256', 'b'*64), ('app_offset', '0x410000'),
    ('detector_mode', 'DET_MODE_90'), ('non_app_write_allowed', True),
])
def test_manifest_contents_cannot_authorize_another_image_or_scope(images, monkeypatch, field, value):
    changed = json.loads(images.manifest.read_text())
    changed[field] = value
    # Even an independently hash-checked manifest is constrained by constants.
    monkeypatch.setattr(installer, 'INSTALL_MANIFEST_SHA', save(images.manifest, changed))
    with pytest.raises(ValueError, match='manifest_not_exact_approved_timer_image'):
        installer.validate_images(images)
    assert not images.report_dir.exists()


@pytest.mark.parametrize('restore', [False, True])
def test_files_only_checks_exact_pair_without_serial_or_subprocess(images, monkeypatch, restore):
    if restore:
        reverse(images)
    images.files_only = True

    def denied(*args, **kwargs):
        pytest.fail('files-only reached hardware, subprocess or report directory')

    monkeypatch.setattr(installer.core, 'uart_status', denied)
    monkeypatch.setattr(installer.core, 'run_esptool', denied)
    monkeypatch.setattr(installer.core.subprocess, 'run', denied)
    monkeypatch.setattr(installer.core, 'private_directory', denied)
    report = installer.perform(images)
    assert report['direction'] == ('restore_verified_predecessor' if restore else 'install_candidate')
    assert report['board_identity_security_checked_by_installer'] is False
    assert report['factory_backups_checked_by_installer'] is False
    assert not images.report_dir.exists()


@pytest.mark.parametrize('kind', ['third_image', 'same_image', 'wrong_current_version'])
def test_only_exact_distinct_pair_and_expected_running_version(images, kind):
    if kind == 'third_image':
        images.target_sha = 'f'*64
    elif kind == 'same_image':
        images.target_sha = images.current_sha
    else:
        images.expected_current_version = installer.CANDIDATE_VERSION
    with pytest.raises(ValueError, match='images_must_be_exact|expected_current_version_mismatch'):
        installer.validate_images(images)


@pytest.mark.parametrize('restore', [False, True])
def test_one_app_write_retains_rom_metadata_and_attempt_barriers(images, simulated_device, restore):
    if restore:
        reverse(images)
    events, _ = simulated_device
    images.execute = True
    report = installer.perform(images)
    assert [event[0] for event in events] == [
        'uart', 'read', 'read', 'verify', 'write', 'verify', 'read', 'read', 'uart']
    assert report['app_write_verified'] is True
    assert report['before'] == report['after']
    assert report['status'] == 'app_verified_metadata_preserved_boot_ready'
    assert report['non_app_write_allowed'] is False and report['nvs_read'] is False
    assert report['whole_flash_read'] is False
    event_count = len(events)
    with pytest.raises(ValueError, match='attempt_marker_exists_no_automatic_retry'):
        installer.perform(images)
    assert len(events) == event_count


@pytest.mark.parametrize('restore', [False, True])
def test_owner_mute_blocks_normal_install_and_restore_before_rom(images, monkeypatch, restore):
    if restore:
        reverse(images)
    images.execute = True
    uart = lambda *args: {'muted': '1'}
    monkeypatch.setattr(installer.core, 'uart_status', uart)
    monkeypatch.setattr(installer.core, 'run_esptool', lambda *args, **kwargs:
                        pytest.fail('muted owner reached ROM operation'))
    with pytest.raises(ValueError, match='owner_mute_deployment_deferred'):
        installer.perform(images)
    assert installer.core.uart_status is uart
    assert not list(images.report_dir.glob('attempt-*.json'))


def test_boot_failure_exception_never_applies_to_forward_install(images):
    images.recover_known_boot_failure = True
    with pytest.raises(ValueError, match='requires_exact_candidate_to_v4_restore'):
        installer.perform(images)
    assert not images.report_dir.exists()


def test_boot_failure_reverse_still_requires_exact_running_candidate_rom(images, simulated_device, monkeypatch):
    reverse(images)
    images.recover_known_boot_failure = True
    images.execute = True
    events, original = simulated_device

    def wrong_app(*args, **kwargs):
        if args[3] == 'verify-current-app':
            raise ValueError('candidate_rom_mismatch')
        original(*args, **kwargs)

    monkeypatch.setattr(installer.core, 'run_esptool', wrong_app)
    with pytest.raises(ValueError, match='candidate_rom_mismatch'):
        installer.perform(images)
    assert [event[0] for event in events] == ['read', 'read']
    assert not list(images.report_dir.glob('attempt-*.json'))


def test_unknown_write_does_not_retry_or_report_verified(images, simulated_device, monkeypatch):
    events, original = simulated_device
    images.execute = True

    def interrupted(*args, **kwargs):
        original(*args, **kwargs)
        if args[1] == 'write':
            raise TimeoutError('synthetic interrupted serial write')

    monkeypatch.setattr(installer.core, 'run_esptool', interrupted)
    with pytest.raises(TimeoutError):
        installer.perform(images)
    marker = json.loads(next(images.report_dir.glob('attempt-*.json')).read_text())
    report = json.loads((Path(marker['report_directory'])/'report.json').read_text())
    assert marker['partial_write_possible'] is True and marker['automatic_retry'] is False
    assert report['app_write_verified'] is False
    assert sum(event[0] == 'write' for event in events) == 1
    with pytest.raises(ValueError, match='attempt_marker_exists_no_automatic_retry'):
        installer.perform(images)
    assert sum(event[0] == 'write' for event in events) == 1
