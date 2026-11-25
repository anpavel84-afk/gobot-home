"""One authorized v420 -> v421 app-only install on the existing PLAN terminal.

The immutable source runtime is left running. Only its owned Gateway is stopped
while the existing app installer owns USB. No transcripts, raw audio, credentials,
NVS or full flash are read/exported. Existing recovery files are hashed locally.
The script never creates a timer, playback, model response, policy or grant.
An uncertain write is recorded and is never repeated automatically.
"""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
import urllib.parse
import urllib.request

ROOT = Path(r'C:\Users\PLAN\gobot\GoBotHome')
PRIVATE = ROOT.parent/'HOST-INTEGRATOR-private'
PACKAGE = PRIVATE/'timer-v421-install-tools'
HEAD = 'e95843386d969b9e736dd848eabaaecbe362a029'
RUNTIME = 'b2a19f9946e7d99a4b91b94bed97b40b828b717d'
BRANCH = 'feat/host-integrator-sophia-unified-20261118'
OLD_VERSION = '0.4.20-dev-sophia-duck-v4'
NEW_VERSION = '0.4.21-dev-sophia-timer-v4'
OLD_SHA = '11956a9e4700c6c53f49ba03c3f3f12daae208d010c319305b2a9d704d52388e'
NEW_SHA = '2e0898e708728973561f3920ddcbebc3c744a488bbf8cac95c72b62891edd68b'
FACTORY_SHA = '1fe1e310d86425dbe2432133c8712aecb64262bb3649647a5104989de671f4e6'
DEPLOYER_SHA = '563b114e877febde9eedad4da411dea191801492019db21b97b011fac8cc20b2'
POSTCHECK_SHA = '37c35ed53ebb0c4650c37a881c3c3a4238cce7c4a5e9016faa035557e0223723'
HW_PYTHON = ROOT/'data/hardware/venv/Scripts/python.exe'
OLD_IMAGE = PRIVATE/'sophia-duck-v4-0.4.20.bin'
NEW_IMAGE = PRIVATE/'sophia-timer-v421-2e0898e70872.bin'
FIRST_RESULT = PRIVATE/'sophia-timer-v421-firmware-deployment-2e0898e70872.json'
FIRST_RECEIPT_SHA = 'b1cc7730a66a6d6c6428dfbff4088c1a5f33243d8c6433dc9f5b6c6e3af0cace'
FIRST_OUTPUT = PRIVATE/'sophia-timer-v421-install-1795513384203727300'
ATTEMPT = PRIVATE/'sophia-timer-v421-firmware-attempt02-2e0898e70872.json'
RESULT = PRIVATE/'sophia-timer-v421-firmware-deployment02-2e0898e70872.json'


def require(value, code):
    if not value:
        raise RuntimeError(code)


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(path, value, *, exclusive=False):
    with Path(path).open('x' if exclusive else 'w', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())


def load(path, expected):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), 'checked_helper_missing')
    raw = path.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == expected, 'checked_helper_changed')
    spec = importlib.util.spec_from_file_location('timer_install_'+path.stem, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    exec(compile(raw, str(path), 'exec'), module.__dict__)
    return module


def metadata(value):
    keys = ('installed', 'firmware', 'candidate_sha256', 'runtime_code_commit',
            'app_write_verified', 'partition_and_ota_unchanged', 'usb_identity_verified',
            'factory_backups_verified', 'source_wip_preserved', 'configuration_preserved',
            'usage_rows_preserved', 'usage_unchanged', 'memory_preserved', 'postcheck_passed',
            'display_supported', 'display_state', 'provider_acknowledged', 'gateway_restarted',
            'failure_code', 'readiness_pending', 'automatic_retry', 'new_model_calls',
            'firmware_unknown', 'partial_write_possible',
            'physical_audio_accepted', 'physical_countdown_accepted', 'private_receipt')
    return {key: value[key] for key in keys if key in value}


def checked_factory_files():
    paths = (ROOT/'data/hardware/factory/spotpear-factory-full-20261112.bin',
             Path(os.environ['LOCALAPPDATA'])/'GoBotHome/FactoryBackups/spotpear-factory-full-20261112.bin',
             ROOT/'data/hardware/gobot-v1/preflash-current.bin')
    for path in paths:
        require(path.is_file() and not path.is_symlink() and path.stat().st_size == 16777216
                and sha(path) == FACTORY_SHA, 'factory_backup_not_verified')
    return {'count': len(paths), 'bytes_each': 16777216, 'sha256': FACTORY_SHA}


def checked_security(text, expected_mac):
    require(isinstance(expected_mac, str) and re.fullmatch(r'(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}', expected_mac),
            'enrolled_mac_invalid')
    macs = re.findall(r'(?im)^\s*MAC:\s*((?:[0-9a-f]{2}:){5}[0-9a-f]{2})\s*$', text['read-mac'])
    require(bool(macs) and {mac.lower() for mac in macs} == {expected_mac.lower()},
            'enrolled_usb_identity_mismatch')
    require('Detected flash size: 16MB' in text['flash-id'], 'unexpected_flash_geometry')
    require(all(item in text['get-security-info'] for item in (
        'Secure Boot: Disabled', 'Flash Encryption: Disabled')), 'unexpected_security_state')
    return {'enrolled_mac_match': True, 'flash_bytes': 16777216,
            'secure_boot_disabled': True, 'flash_encryption_disabled': True}


def checked_first_prewrite_failure(expected_mac):
    """A manually reviewed duplicate banner is not an uncertain app-write retry."""
    require(sha(FIRST_RESULT) == sha(FIRST_OUTPUT/'result.json') == FIRST_RECEIPT_SHA,
            'reviewed_prewrite_receipt_changed')
    value = read(FIRST_RESULT)
    require(value.get('failure_code') == 'enrolled_usb_identity_mismatch'
            and value.get('installed') is False and value.get('candidate_sha256') == NEW_SHA
            and value.get('gateway_restarted') is True and value.get('usage_unchanged') is True
            and value.get('source_wip_preserved') is True and value.get('configuration_preserved') is True
            and value.get('memory_preserved') is True
            and not any(key in value for key in ('installation', 'installer_marker', 'installer_child_started')),
            'previous_attempt_not_proven_prewrite')
    require(not (FIRST_OUTPUT/'installer.log').exists()
            and not list((FIRST_OUTPUT/'installer').glob('attempt-*.json'))
            and not list((FIRST_OUTPUT/'installer').glob('preflight-*')),
            'previous_installer_may_have_started')
    texts = {name: re.sub(r'\x1b\[[0-9;]*m', '', (FIRST_OUTPUT/(name+'.log')).read_text(
                encoding='utf-8', errors='replace')) for name in ('read-mac', 'flash-id', 'get-security-info')}
    checked_security(texts, expected_mac)
    return {'reason': 'same_enrolled_mac_repeated_in_esptool_banner',
            'previous_app_write_started': False, 'previous_receipt_sha256': FIRST_RECEIPT_SHA,
            'prior_receipts_preserved': True, 'unknown_write_retry': False}


def checked_idle_session(session, *, attached):
    require(session.get('muted') is False and session.get('expert_active') is False
            and session.get('input_mode') == 'fast', 'physical_owner_activity_or_mute')
    lifecycle = session.get('lifecycle', {})
    timers = lifecycle.get('timers', {})
    require(timers.get('output_active') is False and type(timers.get('pending_claims')) is int
            and timers['pending_claims'] == 0, 'timer_output_active_or_unknown')
    if attached:
        require(session.get('state') == 'ready' and session.get('ready') is True
                and session.get('capture_connected') is True and lifecycle.get('attached') is True,
                'physical_transport_not_ready')
    else:
        require(session.get('state') == 'detached' and session.get('capture_connected') is False
                and lifecycle.get('attached') is False, 'physical_detach_not_confirmed')


def main(execute, installer_sha):
    import psutil

    require(re.fullmatch('[a-f0-9]{64}', installer_sha) is not None, 'installer_hash_required')
    os.chdir(ROOT)
    dep = load(PRIVATE/'host_integrator_live_skills_deploy.py', DEPLOYER_SHA)
    post = load(PRIVATE/'host_integrator_live_skills_postcheck.py', POSTCHECK_SHA)
    require(dep.git('rev-parse', 'HEAD') == HEAD and dep.git('branch', '--show-current') == BRANCH,
            'installed_source_head_changed')
    paths = {'source_receipt': PRIVATE/('sophia-live-skills-current-'+RUNTIME[:12]+'.json'),
             'source_deployment': PRIVATE/('sophia-live-skills-source-deployment-'+RUNTIME[:12]+'.json'),
             'windows_gate': PRIVATE/('sophia-live-skills-gate-'+RUNTIME[:12])/'receipt.json',
             'deployer': PRIVATE/'host_integrator_live_skills_deploy.py'}
    post.checked_deployment_receipts(RUNTIME, paths)
    installer_path = PACKAGE/'tools/sophia_timer_app_install.py'
    installer = load(installer_path, installer_sha)
    ui = dep.helper('host_integrator_feedback_ui.py')
    joint = dep.helper('host_integrator_joint_activate.py')
    account = dep.helper('host_integrator_wake_barge_apply.py')
    verify = dep.helper('host_integrator_wake_barge_verified_publish.py')
    verify.SOURCE = RUNTIME
    deployed = read(PRIVATE/'wake-barge-source-deployment-66fcae045c74.json')
    origin = read(verify.ORIGIN_DEPLOYMENT)
    config = read(ROOT/'data/hardware/gobot-v1/gateway.json')
    token = read(ROOT/'run/keys.json')['api_token']
    query = urllib.parse.urlencode({'source': 'device', 'device_id': config['device_id'],
                                   'client_id': config['device_id']})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def native(path):
        request = urllib.request.Request('http://127.0.0.1:18781'+path,
            headers={'Authorization': 'Bearer '+token}, method='GET')
        with opener.open(request, timeout=6) as response:
            require(response.status == 200, 'runtime_status_unavailable')
            raw = response.read(2000001)
            require(len(raw) <= 2000000, 'runtime_status_too_large')
            return json.loads(raw)

    def require_idle(*, attached):
        runtime = native('/api/v1/status')
        require(runtime.get('runtime_code_commit') == RUNTIME, 'runtime_changed')
        values = [runtime.get('active_turns'), runtime.get('active_voice_streams')]
        for path in ('/api/v1/realtime/status', '/api/v1/voice-ab/b/status', '/api/v1/live/status'):
            values.append(native(path).get('active_sessions'))
        browser = native('/api/v1/voice-ws/status?source=browser')['status']
        values.extend((browser.get('active_inputs'), browser.get('active_sessions')))
        direct = native('/api/v1/voice-ws/status?'+query)
        values.append(direct['status'].get('active_inputs'))
        require(all(type(n) is int and n == 0 for n in values), 'owner_active_or_status_unknown')
        sessions = direct.get('sessions')
        require(isinstance(sessions, list) and len(sessions) == direct['status'].get('active_sessions')
                and len(sessions) <= 1, 'physical_session_count_unknown')
        for session in sessions:
            checked_idle_session(session, attached=attached)
        if attached:
            require(len(sessions) == 1 and sessions[0].get('ready') is True
                    and sessions[0].get('capture_connected') is True
                    and sessions[0].get('lifecycle', {}).get('attached') is True,
                    'physical_transport_not_ready')
            gateway = read(ROOT/'data/hardware/gobot-v1/gateway-status.json')['unified']
            gateway_age = time.time()-(ROOT/'data/hardware/gobot-v1/gateway-status.json').stat().st_mtime
            require(gateway.get('cloud_ready') is True and gateway.get('device_protocol_confirmed') is True
                    and gateway.get('input_open') is False and gateway.get('last_error') is None
                    and -1 <= gateway_age < 15,
                    'gateway_not_idle')
        dep.require_memory_background_idle()
        return sessions[0] if sessions else None

    def wait_detached_idle():
        deadline = time.monotonic()+10
        while True:
            try:
                return require_idle(attached=False)
            except RuntimeError as error:
                if str(error) != 'physical_detach_not_confirmed' or time.monotonic() >= deadline:
                    raise
                time.sleep(.25)

    output = PRIVATE/('sophia-timer-v421-install-'+str(time.time_ns()))
    output.mkdir()
    report_dir = output/'installer'
    report_dir.mkdir()
    report = {'installed': False, 'runtime_code_commit': RUNTIME, 'head': HEAD,
              'candidate_sha256': NEW_SHA, 'previous_firmware': OLD_VERSION,
              'previous_sha256': OLD_SHA, 'automatic_retry': False, 'new_model_calls': 0,
              'nvs_read': False, 'nvs_writes': False, 'whole_flash_read': False,
              'physical_audio_accepted': False, 'physical_countdown_accepted': False,
              'started_at': time.time(), 'source_restart': False, 'gateway_restarted': False,
              'installer_sha256': installer_sha, 'orchestrator_sha256': sha(__file__)}
    maintenance = False
    attempted = False
    before = None
    memory_guard = None
    entry = read(Path(read(ROOT/'run/host-integrator-deploy-pointer.json')['backup'])/'deployment.json')['processes']['gateway']

    def gateway():
        pids = {item.pid for item in psutil.net_connections(kind='tcp')
                if item.status == 'LISTEN' and item.laddr.port == 18789}
        require(len(pids) <= 1, 'ambiguous_gateway_listener')
        if not pids:
            return None
        process = psutil.Process(next(iter(pids)))
        require(process.cmdline() == entry['cmd'] and process.cwd() == entry['cwd'], 'gateway_process_not_owned')
        return process

    def stop_gateway():
        process = gateway()
        require(process is not None, 'existing_gateway_missing')
        created = process.create_time()
        again = gateway()
        require(again.pid == process.pid and abs(again.create_time()-created) < .1, 'gateway_identity_changed')
        process.terminate()
        process.wait(timeout=8)
        require(gateway() is None, 'gateway_stop_incomplete')

    def start_gateway():
        if gateway() is None:
            env = os.environ.copy()
            env['PYTHONUTF8'] = '1'
            env['PYTHONUNBUFFERED'] = '1'
            with (ROOT/'run/host-integrator-gateway.log').open('ab') as log:
                subprocess.Popen(entry['cmd'], cwd=entry['cwd'], env=env, stdin=subprocess.DEVNULL,
                    stdout=log, stderr=log, creationflags=0x08000000)
        deadline = time.monotonic()+30
        while time.monotonic() < deadline:
            if gateway() is not None:
                report['gateway_restarted'] = True
                return
            time.sleep(.5)
        raise RuntimeError('gateway_restart_timeout')

    terminal_paths = {str(verify.GRANT/'usage.sqlite'), str(verify.GRANT/'experts/usage.sqlite')}
    protected_paths = [ROOT/'run/keys.json', ROOT/'data/hardware/gobot-v1/gateway.json',
                       ROOT/'run/voice-ab-b/mount.json', verify.GRANT/'owner-authorization.json',
                       ROOT/'data/sophia-admin-owner.json', ROOT/'data/working-memory-policy.json']

    def preservation():
        data = ui.preservation_snapshot()
        require({kind: len(rows) for kind, rows in data.items()} == dep.PRESERVATION_COUNTS,
                'preservation_inventory_changed')
        wip = joint.work_in_progress()
        dep.check_wip_inventory(wip)
        require(wip[str(ROOT)]['head'] == HEAD, 'checkout_changed')
        return {'data': data, 'wip': wip,
                'terminal_rows': {p: account.terminal_rows(Path(p)) for p in terminal_paths},
                'protected': {str(p): sha(p) for p in protected_paths},
                'scope': verify.scope_binding(deployed, origin), 'serve_hash': dep.tailscale()}

    def preserved():
        after = preservation()
        require(all(after[key] == before[key] for key in ('wip', 'protected', 'scope', 'serve_hash')),
                'protected_wip_configuration_or_scope_changed')
        require({kind: set(rows) for kind, rows in before['data'].items()} ==
                {kind: set(rows) for kind, rows in after['data'].items()}, 'preservation_paths_changed')
        for kind, rows in before['data'].items():
            for path, expected in rows.items():
                if kind == 'ledgers' and path in terminal_paths:
                    account.require_terminal_extension(before['terminal_rows'][path], after['terminal_rows'][path])
                else:
                    require(after['data'][kind][path] == expected, 'protected_'+kind+'_changed')
        if memory_guard:
            memory_guard.preserve(require_timer_schema=True)
            report['memory_preserved'] = True
        report.update(source_wip_preserved=True, configuration_preserved=True, usage_rows_preserved=True,
                      usage_unchanged=before['data']['ledgers'] == after['data']['ledgers'])
        return after

    def installer_args(reverse=False, files_only=False):
        values = ['--current-image', str(NEW_IMAGE if reverse else OLD_IMAGE),
                  '--current-sha', NEW_SHA if reverse else OLD_SHA,
                  '--target-image', str(OLD_IMAGE if reverse else NEW_IMAGE),
                  '--target-sha', OLD_SHA if reverse else NEW_SHA,
                  '--expected-current-version', NEW_VERSION if reverse else OLD_VERSION,
                  '--port', 'COM3', '--report-dir', str(report_dir),
                  '--attempt-id', 'timer-v421-restore' if reverse else 'timer-v421-first']
        values.append('--files-only' if files_only else '--execute')
        return values

    def collect_installation():
        marker = report_dir/('attempt-timer-v421-first-'+OLD_SHA[:12]+'-'+NEW_SHA[:12]+'.json')
        try:
            if marker.is_file():
                value = read(marker)
                require(isinstance(value, dict), 'installer_marker_invalid')
                report['installer_marker'] = value
                receipt = Path(value['report_directory'])/'report.json'
                if receipt.is_file():
                    installation = read(receipt)
                    require(isinstance(installation, dict), 'installer_report_invalid')
                    report['installation'] = installation
                else:
                    report['installer_report_unavailable'] = True
            else:
                preflights = sorted(report_dir.glob('preflight-*/report.json'))
                if len(preflights) == 1:
                    installation = read(preflights[0])
                    require(isinstance(installation, dict), 'installer_report_invalid')
                    report['installation'] = installation
                elif report.get('installer_child_started'):
                    report['installer_report_unavailable'] = True
        except (OSError, ValueError, RuntimeError, KeyError, TypeError):
            # The core flushes durable write intent separately from report.json;
            # a process death may truncate either file. Keep the known marker
            # and let the outer failure path mark an uncertain image, not success.
            report['installer_report_unavailable'] = True

    try:
        require(not ATTEMPT.exists() and not RESULT.exists(), 'prior_attempt_requires_inspection_no_retry')
        report['reviewed_prewrite_failure'] = checked_first_prewrite_failure(config.get('device_mac'))
        require_idle(attached=True)
        report['factory_backups'] = checked_factory_files()
        report['factory_backups_verified'] = True
        report['files_forward'] = installer.perform(installer.parser().parse_args(installer_args(files_only=True)))
        report['files_reverse'] = installer.perform(installer.parser().parse_args(installer_args(reverse=True, files_only=True)))
        before = preservation()
        save(output/'before.json', before, exclusive=True)
        if not execute:
            report['files_and_idle_preflight_passed'] = True
            return report
        # The current running source already passed its gate; no source checkout or restart.
        startup_path = ROOT/'tools/sophia_terminal_startup.py'
        committed = subprocess.check_output(['git', '-C', str(ROOT), 'show', HEAD+':tools/sophia_terminal_startup.py'])
        startup = load(startup_path, hashlib.sha256(committed).hexdigest())
        specs = startup.load_specs(ROOT)
        system = startup.WindowsSystem()
        owner = system.current_owner()
        memory_guard = dep.MemoryGuard(RUNTIME, {'memory_db': 'data/gobot.sqlite'}, verify, deployed,
            origin, output, startup, system, specs, owner)
        report['memory_guard'] = memory_guard.receipt
        require_idle(attached=True)
        preserved()
        save(ATTEMPT, {'state': 'started', 'candidate_sha256': NEW_SHA, 'output': str(output),
                      'started_at': time.time(), 'automatic_retry': False}, exclusive=True)
        attempted = True
        maintenance = True
        stop_gateway()
        wait_detached_idle()
        print(json.dumps({'firmware_stage': 'gateway_paused_identity_preflight', 'new_model_calls': 0}), flush=True)
        # This no-reset UART guard observes user mute before ROM resets can erase its RAM state.
        uart_result = subprocess.run([str(HW_PYTHON), '-B', '-X', 'utf8', str(Path(__file__)),
            '--installer-sha256', installer_sha, '--uart-status'], capture_output=True,
            text=True, encoding='utf-8', timeout=45, stdin=subprocess.DEVNULL)
        require(uart_result.returncode == 0, 'uart_identity_preflight_failed')
        uart_before = json.loads(uart_result.stdout)
        require(uart_before.get('muted') == '0', 'owner_mute_deployment_deferred')
        report['uart_identity_preflight'] = uart_before
        rom = {}
        for operation in ('read-mac', 'flash-id', 'get-security-info'):
            argv = [str(HW_PYTHON), '-B', '-m', 'esptool', '--chip', 'esp32s3', '--port', 'COM3',
                    '--baud', '460800', '--connect-attempts', '3', '--before', 'default-reset',
                    '--after', 'hard-reset', operation]
            result = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=90)
            (output/(operation+'.log')).write_bytes(result.stdout)
            require(result.returncode == 0, 'rom_identity_preflight_failed')
            rom[operation] = re.sub(r'\x1b\[[0-9;]*m', '', result.stdout.decode('utf-8', errors='replace'))
        report['usb_identity'] = checked_security(rom, config.get('device_mac'))
        report['usb_identity_verified'] = True
        require_idle(attached=False)
        preserved()
        print(json.dumps({'firmware_stage': 'verified_identity_single_app_attempt', 'new_model_calls': 0}), flush=True)
        try:
            report['installer_child_started'] = True
            with (output/'installer.log').open('xb') as log:
                completed = subprocess.run([str(HW_PYTHON), '-B', '-X', 'utf8', str(installer_path),
                    *installer_args()], cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log,
                    stderr=subprocess.STDOUT, timeout=1080)
        finally:
            collect_installation()
        installation = report.get('installation', {})
        require(completed.returncode == 0 and installation.get('app_write_verified') is True
                and installation.get('status') == 'app_verified_metadata_preserved_boot_ready'
                and installation.get('restore_image_matches_active_flash') is True
                and installation.get('target', {}).get('sha256') == NEW_SHA
                and installation.get('before') == installation.get('after')
                and installation.get('uart_after', {}).get('version') == NEW_VERSION,
                'installation_not_verified_inspect_private_report')
        report.update(installed=True, firmware=NEW_VERSION, app_write_verified=True,
                      partition_and_ota_unchanged=True)
        start_gateway()
        maintenance = False
        deadline = time.monotonic()+90
        final = None
        while time.monotonic() < deadline:
            try:
                final = require_idle(attached=True)
                timers = final.get('lifecycle', {}).get('timers', {})
                require(timers.get('display_supported') is True and timers.get('capabilities_received') is True,
                        'timer_display_capability_not_confirmed')
                admin = json.loads(dep.get('http://127.0.0.1:18811/api/sophia/admin/snapshot'))
                conversation = dep.checked_conversation_status(final, admin.get('settings', {}).get('conversation'))
                report['conversation'] = conversation
                report.update(display_supported=True, display_state=timers.get('display_state'),
                              provider_acknowledged=True)
                break
            except (RuntimeError, OSError, ValueError):
                time.sleep(.5)
        else:
            raise RuntimeError('installed_readiness_pending')
        postcheck = post.main(RUNTIME)
        save(output/'postcheck.json', postcheck, exclusive=True)
        require(postcheck.get('passed') is True, 'postcheck_failed')
        report['postcheck'] = postcheck
        report['postcheck_passed'] = True
        preserved()
        report['memory_guard'] = memory_guard.receipt
    except BaseException as error:
        collect_installation()
        installation = report.get('installation', {})
        if installation.get('app_write_verified') is True:
            report.update(installed=True, firmware=NEW_VERSION, app_write_verified=True, readiness_pending=True)
        elif (installation.get('app_write_started') is True or
              report.get('installer_marker', {}).get('state') in {'write_started', 'failed_no_retry'} or
              (report.get('installer_child_started') and report.get('installer_report_unavailable'))):
            report.update(firmware_unknown=True, partial_write_possible=True, readiness_pending=True)
        report['failure_code'] = str(error) if isinstance(error, (RuntimeError, ValueError)) and re.fullmatch(
            '[a-z0-9_]+', str(error)) else 'inspect_private_report'
        report['failure_type'] = type(error).__name__
        if before:
            try:
                preserved()
            except Exception:
                report['preservation_pending_inspection'] = True
    finally:
        if maintenance:
            try:
                start_gateway()
            except Exception:
                report['gateway_restart_pending_inspection'] = True
        report['finished_at'] = time.time()
        report['private_receipt'] = str(output/'result.json')
        save(output/'result.json', report, exclusive=True)
        if attempted:
            save(RESULT, report, exclusive=True)
        print(json.dumps(metadata(report)), flush=True)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--installer-sha256', required=True)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--uart-status', action='store_true')
    args = parser.parse_args()
    try:
        require(not (args.execute and args.uart_status), 'conflicting_execution_modes')
        if args.uart_status:
            installer = load(PACKAGE/'tools/sophia_timer_app_install.py', args.installer_sha256)
            state = installer.core.uart_status('COM3', OLD_VERSION)
            require(state.get('muted') == '0', 'owner_mute_deployment_deferred')
            print(json.dumps(state), flush=True)
            raise SystemExit(0)
        result = main(args.execute, args.installer_sha256)
        success = result.get('postcheck_passed') if args.execute else result.get('files_and_idle_preflight_passed')
        raise SystemExit(0 if success else 1)
    except Exception as error:
        code = str(error) if isinstance(error, (RuntimeError, ValueError)) and re.fullmatch(
            '[a-z0-9_]+', str(error)) else 'inspect_private_report'
        print(json.dumps({'installed': False, 'error_code': code, 'automatic_retry': False}), flush=True)
        raise SystemExit(1)
