"""Free process/receipt tests; no subprocess, provider, COM or real listener."""
import copy
import importlib.util
import json
from pathlib import Path
import sys

import pytest


SOURCE = Path(__file__).resolve().parents[1] / "tools/sophia_terminal_startup.py"
SPEC = importlib.util.spec_from_file_location("sophia_terminal_startup_tested", SOURCE)
m = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = m
SPEC.loader.exec_module(m)
OWNER = "TEST-PC\\PLAN"


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


@pytest.fixture
def root(tmp_path):
    root = tmp_path / "GoBotHome"
    files = [root / ".venv/Scripts/python.exe", root / "scripts/manage.py",
             root / "services/voice/gobot_device_gateway.py",
             root / "data/hardware/gobot-v1/gateway.json",
             root / "data/hardware/gobot-v1/server.pem", root / "data/hardware/gobot-v1/server.key",
             root.parent / "GoBotHome-host-A/tools/host_a_browser_voice_lab.py"]
    for path in files:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture", encoding="utf-8")
    write(root / "run/keys.json", {k: "existing-private-value" for k in
          ("api_token", "bridge_secret", "device_token", "device_secret")})
    backup = root.parent / "HOST-INTEGRATOR-private/deploy-known"
    write(root / "run/host-integrator-deploy-pointer.json", {"backup": str(backup)})
    python = str(root / ".venv/Scripts/python.exe")
    processes = {
        "gateway": {"pid": 11, "created": 10., "cmd": [python, "-u",
            str(root / "services/voice/gobot_device_gateway.py"), "--config",
            str(root / "data/hardware/gobot-v1/gateway.json")], "cwd": str(root), "port": 18789},
        "browser": {"pid": 12, "created": 10., "cmd": [python, "-u",
            str(root.parent / "GoBotHome-host-A/tools/host_a_browser_voice_lab.py")],
            "cwd": str(root), "port": 18811},
    }
    write(backup / "deployment.json", {"processes": processes})
    # Existing accounting/config bytes must survive every successful startup.
    write(root / "run/owner-terminal/policy.json", {"permanent": True})
    (root / "run/owner-terminal/usage.sqlite").write_bytes(b"fixture-existing-usage")
    return root


def process(pid, command, root, *, created=None, ppid=1, owner=OWNER):
    return {"pid": pid, "created": float(created if created is not None else pid + 1000),
            "cmd": list(command), "cwd": str(root), "owner": owner, "ppid": ppid}


class FakeSystem:
    def __init__(self, root):
        self.root = root
        self.processes = {}
        self.listeners = {}
        self.calls = []
        self.next_pid = 300
        self.owner = OWNER
        self.reuse_child_pid = False

    def current_owner(self):
        return self.owner

    def snapshot(self):
        return copy.deepcopy({"processes": self.processes, "listeners": self.listeners})

    def add_core(self):
        root = self.root
        specs = m.load_specs(root)
        command = (str(root / ".venv/Scripts/python.exe"), str(root / "scripts/manage.py"), "supervise")
        supervisor = process(200, command, root)
        self.processes[200] = supervisor
        workers = {}
        for pid, (name, port) in enumerate(m.CORE_PORTS.items(), 201):
            item = process(pid, specs[name].command, root, ppid=200)
            self.processes[pid] = item
            self.listeners[port] = {pid}
            workers[name] = {"pid": pid, "created": item["created"], "port": port}
        write(root / "run/processes.json", {"supervisor": {"pid": 200, "created": supervisor["created"]},
                                             "workers": workers})

    def add_external(self, name, *, pid=None, bind=True, ppid=1):
        spec = m.load_specs(self.root)[name]
        pid = pid or self.next_pid
        self.next_pid = max(self.next_pid + 1, pid + 1)
        item = process(pid, spec.command, self.root, ppid=ppid)
        self.processes[pid] = item
        if bind:
            self.listeners[spec.port] = {pid}
        return {"pid": pid, "created": item["created"]}

    def spawn(self, command, root, label, *, wait=False):
        self.calls.append((tuple(command), label, wait))
        assert Path(root) == self.root
        if wait:
            assert label == "core-start"
            assert command == [str(root / ".venv/Scripts/python.exe"), "-X", "utf8",
                               str(root / "scripts/manage.py"), "start"]
            self.add_core()
            return None
        spec = m.load_specs(root)[label]
        assert tuple(command) == spec.command
        identity = self.add_external(label)
        if self.reuse_child_pid:
            self.processes[identity["pid"]]["created"] += 5
        return identity

    def pause(self):
        pass


def all_bytes(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_default_status_is_read_only_and_start_requires_explicit_execute(root):
    system = FakeSystem(root)
    before = all_bytes(root)
    assert m.parser().parse_args([]).command == "status"
    assert m.perform(root, system=system)["status"] == "stopped"
    with pytest.raises(m.StartupError, match="start_requires_execute"):
        m.perform(root, start=True, system=system)
    assert not system.calls
    assert all_bytes(root) == before


def test_cold_start_uses_only_exact_commands_preserves_data_and_second_start_is_noop(root):
    system = FakeSystem(root)
    before = all_bytes(root)
    result = m.perform(root, start=True, execute=True, system=system)
    assert result["status"] == "running" and result["changed"]
    assert [call[1] for call in system.calls] == ["core-start", "gateway", "browser"]
    for path, content in before.items():
        assert (root / path).read_bytes() == content
    receipt = json.loads((root / "run/sophia-terminal-startup/processes.json").read_text())
    assert set(receipt["processes"]) == {"gateway", "browser"}
    after = all_bytes(root)
    second = m.perform(root, start=True, execute=True, system=system)
    assert second["status"] == "running" and not second["changed"]
    assert len(system.calls) == 3 and all_bytes(root) == after


def test_manual_existing_complete_stack_is_verified_and_never_restarted(root):
    system = FakeSystem(root)
    system.add_core(); system.add_external("gateway"); system.add_external("browser")
    before = all_bytes(root)
    assert m.perform(root, start=True, execute=True, system=system)["reason"] == "existing_stack_untouched"
    assert not system.calls and all_bytes(root) == before


def test_partial_owned_stack_defers_instead_of_touching_owner_work(root):
    system = FakeSystem(root); system.add_core()
    assert m.perform(root, system=system)["status"] == "partial"
    with pytest.raises(m.StartupError, match="partial_stack_operator_inspection_required"):
        m.perform(root, start=True, execute=True, system=system)
    assert not system.calls


@pytest.mark.parametrize("port", [18781, 18782, 18783, 18784, 18789, 18811])
def test_any_foreign_reserved_listener_blocks_before_any_spawn(root, port):
    system = FakeSystem(root)
    system.processes[99] = process(99, ["unrelated.exe"], root)
    system.listeners[port] = {99}
    with pytest.raises(m.StartupError, match="foreign_or_unverifiable_listener"):
        m.perform(root, start=True, execute=True, system=system)
    assert not system.calls


def test_unverifiable_listener_and_wrong_user_are_refused(root):
    system = FakeSystem(root); system.listeners[18811] = {None}
    with pytest.raises(m.StartupError, match="foreign_or_unverifiable_listener"):
        m.perform(root, start=True, execute=True, system=system)
    system.listeners.clear(); system.owner = "NT AUTHORITY\\SYSTEM"
    with pytest.raises(m.StartupError, match="windows_plan_user_required"):
        m.perform(root, start=True, execute=True, system=system)
    assert not system.calls


def test_stale_supervisor_pid_reused_by_unrelated_process_is_never_adopted_or_touched(root):
    system = FakeSystem(root)
    reused = process(117, ["unrelated.exe"], root, created=999)
    system.processes[117] = copy.deepcopy(reused)
    write(root / "run/processes.json", {"supervisor": {"pid": 117, "created": 1.}, "workers": {}})
    assert m.perform(root, start=True, execute=True, system=system)["status"] == "running"
    assert system.processes[117] == reused


def test_reused_worker_pid_or_wrong_supervisor_command_never_passes_manifest_check(root):
    system = FakeSystem(root); system.add_core()
    system.processes[201]["created"] += 2
    with pytest.raises(m.StartupError, match="core_worker_manifest_identity_mismatch"):
        m.perform(root, start=True, execute=True, system=system)
    system.processes[201]["created"] -= 2
    system.processes[200]["cmd"] = ["unrelated.exe"]
    with pytest.raises(m.StartupError, match="core_supervisor_identity_mismatch"):
        m.perform(root, start=True, execute=True, system=system)
    assert not system.calls


def test_duplicate_external_process_and_unrecorded_supervisor_cannot_spawn_more(root):
    system = FakeSystem(root)
    system.add_external("gateway", pid=310)
    system.add_external("gateway", pid=311, bind=False)
    with pytest.raises(m.StartupError, match="duplicate_owned_processes"):
        m.perform(root, start=True, execute=True, system=system)
    system.processes.clear(); system.listeners.clear()
    command = [str(root / ".venv/Scripts/python.exe"), str(root / "scripts/manage.py"), "supervise"]
    system.processes[88] = process(88, command, root)
    with pytest.raises(m.StartupError, match="unrecorded_live_supervisor"):
        m.perform(root, start=True, execute=True, system=system)
    assert not system.calls


def test_exact_windows_venv_child_is_allowed_only_beneath_recorded_parent(root):
    system = FakeSystem(root); system.add_core()
    parent = system.processes[201]
    child = process(901, parent["cmd"], root, ppid=201)
    system.processes[901] = child; system.listeners[18781] = {901}
    assert m.perform(root, system=system)["status"] == "partial"
    system.processes[901]["ppid"] = 1
    with pytest.raises(m.StartupError, match="duplicate_owned_processes"):
        m.perform(root, system=system)


def test_new_external_pid_reuse_is_detected_before_starting_next_component(root):
    system = FakeSystem(root); system.reuse_child_pid = True
    with pytest.raises(m.StartupError, match="new_external_process_identity_lost"):
        m.perform(root, start=True, execute=True, system=system)
    assert [c[1] for c in system.calls] == ["core-start", "gateway"]
    # There is intentionally no terminate/kill operation in the system adapter.
    assert not hasattr(m.WindowsSystem, "stop")


@pytest.mark.parametrize("missing", [True, False])
def test_missing_or_invalid_keys_never_reaches_manager_init(root, missing):
    system = FakeSystem(root); path = root / "run/keys.json"
    if missing:
        path.unlink()
    else:
        write(path, {"api_token": "incomplete"})
    with pytest.raises(m.StartupError, match="existing_keys_.*no_initialization"):
        m.perform(root, start=True, execute=True, system=system)
    assert not system.calls
    assert path.exists() is not missing


@pytest.mark.parametrize("field", ["cmd", "cwd", "port"])
def test_saved_json_cannot_become_arbitrary_execution(root, field):
    system = FakeSystem(root)
    receipt = root.parent / "HOST-INTEGRATOR-private/deploy-known/deployment.json"
    data = json.loads(receipt.read_text())
    data["processes"]["browser"][field] = {"cmd": ["powershell", "-Command", "bad"],
        "cwd": str(root.parent), "port": 8888}[field]
    write(receipt, data)
    with pytest.raises(m.StartupError, match="saved_external_command_not_approved"):
        m.perform(root, start=True, execute=True, system=system)
    assert not system.calls


def test_backup_escape_is_refused_before_reading_arbitrary_deployment(root):
    system = FakeSystem(root)
    write(root / "run/host-integrator-deploy-pointer.json", {"backup": str(root.parent / "elsewhere")})
    with pytest.raises(m.StartupError, match="private_path_unavailable"):
        m.perform(root, start=True, execute=True, system=system)
    assert not system.calls


def test_overlapping_start_uses_one_project_lock(root):
    system = FakeSystem(root)
    with m.launch_lock(root):
        with pytest.raises(m.StartupError, match="startup_already_in_progress"):
            m.perform(root, start=True, execute=True, system=system)
    assert not system.calls


def test_pythonw_no_console_writes_only_sanitized_private_operational_result(root, monkeypatch):
    monkeypatch.setattr(m, "ROOT", root)
    monkeypatch.setattr(m.sys, "argv", ["sophia_terminal_startup.py", "start", "--execute"])
    monkeypatch.setattr(m.sys, "stdout", None)
    def failed(**kwargs):
        raise ValueError("private secret must not be logged")
    monkeypatch.setattr(m, "perform", failed)
    assert m.main() == 1
    logged = (root / "run/sophia-terminal-startup.log").read_text()
    assert "private secret" not in logged
    assert json.loads(logged)["reason"] == "startup_failed_inspect_private_logs"
