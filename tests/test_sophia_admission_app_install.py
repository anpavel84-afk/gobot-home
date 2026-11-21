"""Version-pinned successor and rollback gates; no physical device or model."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_sophia_v4_app_install import app_bytes, digest, metadata


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('sophia_admission_installer',
    ROOT/'tools/sophia_admission_app_install.py')
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)


@pytest.fixture
def images(tmp_path, monkeypatch):
    current, target = tmp_path/'current.bin', tmp_path/'target.bin'
    current.write_bytes(app_bytes(installer.PREDECESSOR_VERSION))
    target.write_bytes(app_bytes(installer.CANDIDATE_VERSION, size=768))
    previous = tmp_path/'previous.json'
    previous.write_text(json.dumps({'candidate_version': installer.PREDECESSOR_VERSION,
        'candidate_app_sha256': digest(current.read_bytes()), 'candidate_app_size': current.stat().st_size}))
    monkeypatch.setattr(installer, 'PREDECESSOR_MANIFEST', previous)
    monkeypatch.setattr(installer, 'PREDECESSOR_MANIFEST_SHA', digest(previous.read_bytes()))
    monkeypatch.setattr(installer, 'PREDECESSOR_SHA', digest(current.read_bytes()))
    monkeypatch.setattr(installer, 'PREDECESSOR_BYTES', current.stat().st_size)
    manifest = tmp_path/'manifest.json'
    manifest.write_text(json.dumps({'parent_manifest_sha256': installer.PREDECESSOR_MANIFEST_SHA,
        'baseline_version': installer.PREDECESSOR_VERSION, 'baseline_app_sha256': installer.PREDECESSOR_SHA,
        'baseline_app_size': installer.PREDECESSOR_BYTES, 'candidate_version': installer.CANDIDATE_VERSION,
        'candidate_app_sha256': digest(target.read_bytes()), 'candidate_app_size': target.stat().st_size,
        'app_offset': '0x20000', 'app_slot_capacity': installer.core.APP_CAPACITY,
        'model': 'wn10_sophia', 'detector_mode': 'DET_MODE_95'}))
    return SimpleNamespace(current_image=current, target_image=target,
        current_sha=installer.PREDECESSOR_SHA, target_sha=digest(target.read_bytes()),
        manifest=manifest, expected_current_version=installer.PREDECESSOR_VERSION,
        port='COM3', report_dir=tmp_path/'private', attempt_id='successor',
        files_only=False, execute=False, recover_known_boot_failure=False)


@pytest.mark.parametrize('field,value', [
    ('parent_manifest_sha256', '0'*64), ('baseline_app_sha256', '0'*64),
    ('baseline_version', '0.4.14-dev-host-b-sophia-mic-v4'),
    ('candidate_version', 'unreviewed'), ('app_offset', '0x410000'),
    ('detector_mode', 'DET_MODE_90'), ('model', 'different'),
])
def test_wrong_successor_or_changed_wake_provenance_is_rejected(images, field, value):
    manifest = json.loads(images.manifest.read_text())
    manifest[field] = value
    images.manifest.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='manifest_not_verified_admission_successor'):
        installer.validate_images(images)
    assert not images.report_dir.exists()


def test_predecessor_manifest_is_independently_pinned(images):
    installer.PREDECESSOR_MANIFEST.write_text('{}')
    with pytest.raises(ValueError, match='verified_predecessor_manifest_changed'):
        installer.validate_images(images)


def test_files_only_validates_both_directions_without_hardware(images, monkeypatch):
    def denied(*args, **kwargs):
        pytest.fail('files-only reached hardware')
    monkeypatch.setattr(installer.core, 'uart_status', denied)
    monkeypatch.setattr(installer.core, 'run_esptool', denied)
    images.files_only = True
    assert installer.perform(images)['direction'] == 'install_candidate'
    images.current_image, images.target_image = images.target_image, images.current_image
    images.current_sha, images.target_sha = images.target_sha, images.current_sha
    images.expected_current_version = installer.CANDIDATE_VERSION
    assert installer.perform(images)['direction'] == 'restore_verified_predecessor'
    assert not images.report_dir.exists()


@pytest.mark.parametrize('restore', [False, True])
def test_successor_uses_existing_single_write_rom_and_metadata_sequence(images, monkeypatch, restore):
    core = installer.core
    partition, ota = metadata()
    original_audit = core.audit_metadata
    monkeypatch.setattr(core, 'audit_metadata', lambda p, o: original_audit(p, o,
        partition_sha=digest(partition), ota_sha=digest(ota)))
    events = []
    if restore:
        images.current_image, images.target_image = images.target_image, images.current_image
        images.current_sha, images.target_sha = images.target_sha, images.current_sha
        images.expected_current_version = installer.CANDIDATE_VERSION
        images.recover_known_boot_failure = True
    images.execute = True

    def uart(port, version):
        events.append(('uart', version))
        return {'version': version, 'wifi': '1', 'enrolled': '1', 'muted': '0', 'phase': '0', 'upload': '1'}

    def esptool(port, operation, run_dir, stage, *, image=None, region=None):
        events.append((operation, stage))
        if operation == 'read':
            image.write_bytes(partition if region == 'partition' else ota)
        if operation == 'write':
            before = json.loads((run_dir/'report.json').read_text())
            assert before['restore_image_matches_active_flash'] is True
            assert ('verify', 'verify-current-app') in events
            marker = json.loads(next(images.report_dir.glob('attempt-*.json')).read_text())
            assert marker['state'] == 'write_started'
            assert marker['target_sha256'] == images.target_sha
            assert core.sha256(image) == images.target_sha

    monkeypatch.setattr(core, 'uart_status', uart)
    monkeypatch.setattr(core, 'run_esptool', esptool)
    report = installer.perform(images)
    assert report['status'] == 'app_verified_metadata_preserved_boot_ready'
    expected = ['read', 'read', 'verify', 'write', 'verify', 'read', 'read', 'uart']
    assert [e[0] for e in events] == (expected if restore else ['uart', *expected])
    assert events[-1] == ('uart', installer.PREDECESSOR_VERSION if restore else installer.CANDIDATE_VERSION)
    assert report['before'] == report['after']
    assert report['non_app_write_allowed'] is False and report['nvs_read'] is False
    with pytest.raises(ValueError, match='attempt_marker_exists_no_automatic_retry'):
        installer.perform(images)


def test_known_boot_recovery_cannot_skip_current_uart_for_install(images):
    images.recover_known_boot_failure = True
    with pytest.raises(ValueError, match='requires_exact_candidate_to_v4_restore'):
        installer.perform(images)
    assert not images.report_dir.exists()


def test_original_installer_rejects_the_new_predecessor_pair(images):
    # The old CLI's pinned V4 boundary has not been widened by the wrapper.
    with pytest.raises(ValueError, match='manifest_not_verified_sophia_v4_basis'):
        installer.core.validate_images(images)
