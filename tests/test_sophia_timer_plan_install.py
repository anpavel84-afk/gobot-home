"""PLAN orchestration guards and failure cleanup; no serial, network or process."""
import ast
import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT/'tools/sophia_timer_plan_install.py'
SPEC = importlib.util.spec_from_file_location('timer_plan_install_tests', SCRIPT)
plan = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(plan)


def session(*, attached=True):
    # The status API exports selected_mode as input_mode. A detach retains the
    # logical session and the configured provider transport, but releases capture.
    return {'state': 'ready' if attached else 'detached', 'ready': True,
            'input_mode': 'fast', 'muted': False, 'expert_active': False,
            'capture_connected': attached,
            'lifecycle': {'attached': attached,
                'timers': {'output_active': False, 'pending_claims': 0}}}


def nested(name, namespace):
    """Run an actual nested guard without entering main or touching hardware."""
    tree = ast.parse(SCRIPT.read_text())
    main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'main')
    definition = next(node for node in main.body if isinstance(node, ast.FunctionDef) and node.name == name)
    code = ast.Module(body=[copy.deepcopy(definition)], type_ignores=[])
    ast.fix_missing_locations(code)
    exec(compile(code, str(SCRIPT), 'exec'), namespace)
    return namespace[name]


@pytest.mark.parametrize('attached', [True, False])
def test_real_api_ready_and_detached_session_shapes_are_supported(attached):
    assert plan.checked_idle_session(session(attached=attached), attached=attached) is None


@pytest.mark.parametrize('path,value', [
    (('muted',), True), (('muted',), None), (('expert_active',), True),
    (('input_mode',), 'expert'), (('input_mode',), 'idle'),
    (('lifecycle', 'timers', 'output_active'), True),
    (('lifecycle', 'timers', 'output_active'), None),
    (('lifecycle', 'timers', 'pending_claims'), 1),
    (('lifecycle', 'timers', 'pending_claims'), -1),
    (('lifecycle', 'timers', 'pending_claims'), False),
    (('lifecycle', 'timers', 'pending_claims'), None),
])
@pytest.mark.parametrize('attached', [True, False])
def test_owner_activity_unknown_timer_state_and_pending_alarm_block_both_phases(path, value, attached):
    current = session(attached=attached)
    child = current
    for key in path[:-1]:
        child = child[key]
    child[path[-1]] = value
    with pytest.raises(RuntimeError):
        plan.checked_idle_session(current, attached=attached)


@pytest.mark.parametrize('attached', [True, False])
@pytest.mark.parametrize('field', ['state', 'capture_connected', 'attached'])
def test_transport_phase_cannot_be_inferred_from_selected_fast_mode(attached, field):
    current = session(attached=attached)
    if field == 'state':
        current['state'] = 'detached' if attached else 'ready'
    elif field == 'attached':
        current['lifecycle']['attached'] = not attached
    else:
        current['capture_connected'] = not attached
    with pytest.raises(RuntimeError, match='physical_transport_not_ready|physical_detach_not_confirmed'):
        plan.checked_idle_session(current, attached=attached)


def test_wait_for_detach_only_retries_transport_settlement():
    calls = []
    now = [10.0]

    def idle(*, attached):
        assert attached is False
        calls.append('idle')
        if len(calls) == 1:
            raise RuntimeError('physical_detach_not_confirmed')
        return session(attached=False)

    namespace = {'require_idle': idle,
                 'time': SimpleNamespace(monotonic=lambda: now[0],
                     sleep=lambda delay: now.__setitem__(0, now[0]+delay))}
    wait = nested('wait_detached_idle', namespace)
    assert wait()['state'] == 'detached'
    assert len(calls) == 2 and now[0] == 10.25


@pytest.mark.parametrize('reason', [
    'physical_owner_activity_or_mute', 'timer_output_active_or_unknown',
    'owner_active_or_status_unknown', 'runtime_changed',
])
def test_owner_activity_and_unknown_status_are_not_polled_away(reason):
    def idle(*, attached):
        raise RuntimeError(reason)

    def denied(delay):
        pytest.fail('owner activity must stop immediately, not be retried')

    wait = nested('wait_detached_idle', {'require_idle': idle,
        'time': SimpleNamespace(monotonic=lambda: 10, sleep=denied)})
    with pytest.raises(RuntimeError, match=reason):
        wait()


@pytest.mark.parametrize('age', [.5, 20, -2])
def test_attached_preflight_requires_fresh_gateway_status(tmp_path, age):
    status_path = tmp_path/'data/hardware/gobot-v1/gateway-status.json'
    status_path.parent.mkdir(parents=True)
    plan.save(status_path, {'unified': {'cloud_ready': True, 'device_protocol_confirmed': True,
                                     'input_open': False, 'last_error': None}})

    def native(path):
        if path == '/api/v1/status':
            return {'runtime_code_commit': plan.RUNTIME, 'active_turns': 0, 'active_voice_streams': 0}
        if path == '/api/v1/voice-ws/status?source=browser':
            return {'status': {'active_inputs': 0, 'active_sessions': 0}}
        if path == '/api/v1/voice-ws/status?device-query':
            return {'status': {'active_inputs': 0, 'active_sessions': 1}, 'sessions': [session()]}
        assert path in {'/api/v1/realtime/status', '/api/v1/voice-ab/b/status', '/api/v1/live/status'}
        return {'active_sessions': 0}

    guard = nested('require_idle', {**plan.__dict__, 'ROOT': tmp_path, 'native': native,
        'query': 'device-query', 'dep': SimpleNamespace(require_memory_background_idle=lambda: None),
        'time': SimpleNamespace(time=lambda: status_path.stat().st_mtime+age)})
    if age == .5:
        assert guard(attached=True)['state'] == 'ready'
    else:
        with pytest.raises(RuntimeError, match='gateway_not_idle'):
            guard(attached=True)


def rom_text():
    return {'read-mac': 'esptool synthetic fixture\nMAC: 02:00:00:00:00:21\n',
            'flash-id': 'Detected flash size: 16MB\n',
            'get-security-info': 'Secure Boot: Disabled\nFlash Encryption: Disabled\n'}


def test_enrolled_board_security_projection_does_not_export_mac():
    result = plan.checked_security(rom_text(), '02:00:00:00:00:21')
    assert result == {'enrolled_mac_match': True, 'flash_bytes': 16777216,
                      'secure_boot_disabled': True, 'flash_encryption_disabled': True}
    assert '02:00:00:00:00:21' not in json.dumps(result)


@pytest.mark.parametrize('repeats', [2, 3])
def test_duplicate_connect_banner_accepts_only_same_enrolled_mac(repeats):
    value = rom_text()
    value['read-mac'] = '\n'.join(['MAC: 02:00:00:00:00:21']*repeats)+'\n'
    assert plan.checked_security(value, '02:00:00:00:00:21')['enrolled_mac_match'] is True
    value['read-mac'] += 'MAC: 02:00:00:00:00:22\n'
    with pytest.raises(RuntimeError, match='enrolled_usb_identity_mismatch'):
        plan.checked_security(value, '02:00:00:00:00:21')


@pytest.fixture
def first_prewrite(tmp_path, monkeypatch):
    output = tmp_path/'first-output'
    (output/'installer').mkdir(parents=True)
    receipt = tmp_path/'first-result.json'
    value = {'failure_code': 'enrolled_usb_identity_mismatch', 'installed': False,
             'candidate_sha256': plan.NEW_SHA, 'gateway_restarted': True,
             'usage_unchanged': True, 'source_wip_preserved': True,
             'configuration_preserved': True, 'memory_preserved': True}
    plan.save(receipt, value)
    (output/'result.json').write_bytes(receipt.read_bytes())
    text = rom_text()
    text['read-mac'] += 'MAC: 02:00:00:00:00:21\n'
    for name, raw in text.items():
        (output/(name+'.log')).write_text(raw)
    monkeypatch.setattr(plan, 'FIRST_RESULT', receipt)
    monkeypatch.setattr(plan, 'FIRST_OUTPUT', output)
    monkeypatch.setattr(plan, 'FIRST_RECEIPT_SHA', plan.sha(receipt))
    return receipt, output, value


def test_reviewed_prewrite_failure_keeps_original_receipts_and_allows_only_new_guarded_attempt(first_prewrite):
    receipt, output, _ = first_prewrite
    before = {str(p): p.read_bytes() for p in [receipt, *(p for p in output.rglob('*') if p.is_file())]}
    checked = plan.checked_first_prewrite_failure('02:00:00:00:00:21')
    assert checked['previous_app_write_started'] is False
    assert checked['unknown_write_retry'] is False and checked['prior_receipts_preserved'] is True
    assert checked['previous_receipt_sha256'] == plan.FIRST_RECEIPT_SHA
    assert all(Path(name).read_bytes() == raw for name, raw in before.items())


@pytest.mark.parametrize('changed_copy', ['first', 'output', 'both'])
def test_altered_or_uncertain_first_receipt_cannot_reuse_approved_hash(first_prewrite, changed_copy):
    receipt, output, value = first_prewrite
    value['partial_write_possible'] = True
    value['firmware_unknown'] = True
    if changed_copy in {'first', 'both'}:
        plan.save(receipt, value)
    if changed_copy in {'output', 'both'}:
        plan.save(output/'result.json', value)
    with pytest.raises(RuntimeError, match='reviewed_prewrite_receipt_changed'):
        plan.checked_first_prewrite_failure('02:00:00:00:00:21')


@pytest.mark.parametrize('field,value', [
    ('installation', {}), ('installer_marker', {'state': 'write_started'}),
    ('installer_child_started', False), ('failure_code', 'installer_timeout'),
    ('installed', True), ('gateway_restarted', False), ('memory_preserved', False),
])
def test_prewrite_semantics_reject_child_evidence_and_incomplete_recovery(
        first_prewrite, monkeypatch, field, value):
    receipt, output, original = first_prewrite
    original[field] = value
    plan.save(receipt, original)
    (output/'result.json').write_bytes(receipt.read_bytes())
    # Exercise semantic checks independently of the outer exact receipt hash.
    monkeypatch.setattr(plan, 'FIRST_RECEIPT_SHA', plan.sha(receipt))
    with pytest.raises(RuntimeError, match='previous_attempt_not_proven_prewrite'):
        plan.checked_first_prewrite_failure('02:00:00:00:00:21')


@pytest.mark.parametrize('artifact', ['installer.log', 'installer/attempt-interrupted.json',
                                    'installer/preflight-incomplete'])
def test_any_prior_installer_artifact_blocks_second_attempt(first_prewrite, artifact):
    _, output, _ = first_prewrite
    path = output/artifact
    if path.name.startswith('preflight-'):
        path.mkdir()
    else:
        path.write_text('')
    with pytest.raises(RuntimeError, match='previous_installer_may_have_started'):
        plan.checked_first_prewrite_failure('02:00:00:00:00:21')


def test_previous_identity_logs_must_still_confirm_same_board(first_prewrite):
    _, output, _ = first_prewrite
    (output/'read-mac.log').write_text('MAC: 02:00:00:00:00:22\n')
    with pytest.raises(RuntimeError, match='enrolled_usb_identity_mismatch'):
        plan.checked_first_prewrite_failure('02:00:00:00:00:21')


@pytest.mark.parametrize('key,text', [
    ('read-mac', 'MAC: 02:00:00:00:00:22\n'),
    ('read-mac', 'MAC: 02:00:00:00:00:21\nMAC: 02:00:00:00:00:22\n'),
    ('read-mac', 'MAC unavailable\n'),
    ('flash-id', 'Detected flash size: 8MB\n'),
    ('get-security-info', 'Secure Boot: Enabled\nFlash Encryption: Disabled\n'),
    ('get-security-info', 'Secure Boot: Disabled\nFlash Encryption: Enabled\n'),
])
def test_wrong_identity_geometry_and_security_block_before_flash(key, text):
    value = rom_text()
    value[key] = text
    with pytest.raises(RuntimeError):
        plan.checked_security(value, '02:00:00:00:00:21')


def test_changed_helper_cannot_execute_before_its_hash_check(tmp_path):
    side_effect = tmp_path/'untrusted-code-ran'
    helper = tmp_path/'unsafe.py'
    helper.write_text('from pathlib import Path\nPath('+repr(str(side_effect))+').touch()\n')
    with pytest.raises(RuntimeError, match='checked_helper_changed'):
        plan.load(helper, '0'*64)
    assert not side_effect.exists()


def test_private_installer_package_resolves_only_its_copied_references(tmp_path):
    package = tmp_path/'timer-v421-install-tools'
    paths = ('tools/sophia_timer_app_install.py', 'tools/sophia_v4_app_install.py',
             'firmware/spotpear/host/sophia_duck_v420_manifest.json',
             'firmware/spotpear/host/sophia_timer_v421_manifest.json',
             'firmware/spotpear/host/sophia_timer_v421_install_manifest.json')
    for name in paths:
        target = package/name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT/name).read_bytes())
    wrapper = package/paths[0]
    copied = plan.load(wrapper, plan.sha(ROOT/paths[0]))
    assert copied.ROOT == copied.core.ROOT == package
    assert copied.CORE_PATH == package/paths[1]
    assert copied.PREDECESSOR_MANIFEST == package/paths[2]
    assert copied.SOURCE_MANIFEST == package/paths[3]
    assert copied.INSTALL_MANIFEST == package/paths[4]
    assert json.loads(copied.INSTALL_MANIFEST.read_text()) == copied.install_contract()


@pytest.mark.parametrize('verified,corrupt_report,corrupt_marker', [
    (False, False, False), (True, False, False), (False, True, False),
    (False, False, True), (False, True, True),
])
def test_write_failure_collects_durable_evidence_and_restores_only_gateway(
        tmp_path, verified, corrupt_report, corrupt_marker, capsys):
    output, report_dir = tmp_path/'output', tmp_path/'output/installer'
    report_dir.mkdir(parents=True)
    core_dir = report_dir/'preflight-synthetic'
    core_dir.mkdir()
    installation = {'app_write_started': True, 'app_write_verified': verified,
                    'partial_write_possible': not verified, 'status': 'failed'}
    marker = report_dir/('attempt-timer-v421-first-'+plan.OLD_SHA[:12]+'-'+plan.NEW_SHA[:12]+'.json')
    if corrupt_marker:
        marker.write_text('{"state": "write_started", "report_directory":')
    else:
        plan.save(marker, {'state': 'write_started', 'report_directory': str(core_dir)}, exclusive=True)
    if corrupt_report:
        (core_dir/'report.json').write_text('{"app_write_started": true, "app_write_ver')
    else:
        plan.save(core_dir/'report.json', installation, exclusive=True)
    report = {'installed': False, 'automatic_retry': False, 'new_model_calls': 0,
              'installer_child_started': True,
              'physical_audio_accepted': False, 'physical_countdown_accepted': False}
    calls = []
    namespace = {**plan.__dict__, 'report': report, 'report_dir': report_dir,
                 'output': output, 'RESULT': tmp_path/'global-result.json',
                 'maintenance': True, 'attempted': True, 'before': None,
                 'start_gateway': lambda: calls.append('gateway'),
                 'injected': TimeoutError('synthetic interrupted or unconfirmed write')}
    nested('collect_installation', namespace)
    tree = ast.parse(SCRIPT.read_text())
    main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'main')
    operation = next(node for node in main.body if isinstance(node, ast.Try))
    # Execute the actual outer failure/finally paths with an interrupted child.
    # Main's process, network and serial body is intentionally never executed.
    failure = ast.Try(body=[ast.Raise(exc=ast.Name(id='injected', ctx=ast.Load()), cause=None)],
                      handlers=copy.deepcopy(operation.handlers), orelse=[],
                      finalbody=copy.deepcopy(operation.finalbody))
    code = ast.Module(body=[failure], type_ignores=[])
    ast.fix_missing_locations(code)
    exec(compile(code, str(SCRIPT), 'exec'), namespace)
    assert calls == ['gateway']
    if not corrupt_report and not corrupt_marker:
        assert report['installation'] == installation
    if not corrupt_marker:
        assert report['installer_marker']['state'] == 'write_started'
    assert report['automatic_retry'] is False and report['new_model_calls'] == 0
    assert report['installed'] is verified
    if verified:
        assert report['firmware'] == plan.NEW_VERSION and report['readiness_pending'] is True
    else:
        assert report['firmware_unknown'] is True and report['partial_write_possible'] is True
        assert report['readiness_pending'] is True
    assert report['physical_audio_accepted'] is False and report['physical_countdown_accepted'] is False
    assert json.loads((tmp_path/'global-result.json').read_text()) == report
    assert json.loads(capsys.readouterr().out)['installed'] is verified


def test_public_metadata_excludes_serial_output_and_private_contents():
    result = plan.metadata({'installed': False, 'automatic_retry': False,
        'usb_identity': {'mac': 'synthetic-private-board'},
        'uart_identity_preflight': {'private': 'not_public'},
        'installation': {'raw_serial': 'not_public'}, 'token': 'synthetic-private-key'})
    assert result == {'installed': False, 'automatic_retry': False}
