"""One-shot recovery of the existing Sophia terminal under Windows user PLAN.

Default is read-only status. ``start --execute`` uses the existing core manager
and two strictly validated deployment commands. This is not a daemon, watchdog,
Windows service, provider probe, grant editor or general command-file executor.
An existing complete stack is left alone. A partial stack requires operator
inspection so a logon cannot interfere with an owner already working.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
CORE_PORTS = {"brain": 18781, "bridge": 18782, "voice": 18783, "images": 18784}
MAX_JSON_BYTES = 262144


class StartupError(RuntimeError):
    """Messages are fixed public codes; never raw command/config/HTTP errors."""


@dataclass(frozen=True)
class Spec:
    name: str
    port: int
    command: tuple[str, ...]
    cwd: Path


def same_path(value, expected):
    if not isinstance(value, str) or not Path(value).is_absolute():
        return False
    return os.path.normcase(os.path.normpath(value)) == os.path.normcase(str(expected))


def same_command(command, expected):
    if not isinstance(command, (list, tuple)) or len(command) != len(expected):
        return False
    for actual, wanted in zip(command, expected):
        if Path(wanted).is_absolute():
            if not same_path(actual, Path(wanted)):
                return False
        elif actual != wanted:
            return False
    return True


def safe_path(path, boundary, *, directory=False):
    path, boundary = Path(path), Path(boundary)
    try:
        path.relative_to(boundary)
        if not path.resolve().is_relative_to(boundary.resolve()):
            raise StartupError("private_path_escape")
        for part in (path, *path.parents):
            if part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction()):
                raise StartupError("private_path_link_refused")
            if part == boundary:
                break
        if not (path.is_dir() if directory else path.is_file()):
            raise StartupError("required_project_file_missing")
    except (ValueError, OSError):
        raise StartupError("private_path_unavailable") from None
    return path


def read_json(path, boundary):
    safe_path(path, boundary)
    try:
        if path.stat().st_size > MAX_JSON_BYTES:
            raise StartupError("project_json_too_large")
        result = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(result, dict):
            raise ValueError()
        return result
    except (OSError, ValueError):
        raise StartupError("project_json_invalid") from None


def valid_identity(entry):
    return (isinstance(entry, dict) and type(entry.get("pid")) is int and entry["pid"] > 0
            and type(entry.get("created")) in (int, float)
            and math.isfinite(entry["created"]) and entry["created"] > 0)


def same_identity(process, entry):
    return (process is not None and valid_identity(entry)
            and process.get("pid") == entry["pid"]
            and type(process.get("created")) in (int, float)
            and abs(process["created"] - entry["created"]) < .1)


def load_specs(root):
    """Read receipts; only the fixed command shapes below can become executable."""
    root = Path(root).resolve()
    private = root.parent / "HOST-INTEGRATOR-private"
    python = root / ".venv/Scripts/python.exe"
    safe_path(python, root)
    safe_path(root / "scripts/manage.py", root)
    keys_path = root / "run/keys.json"
    if not keys_path.is_file():
        # manage.py start invokes init(); never let an absent key file produce
        # a fresh identity and silently detach the enrolled device.
        raise StartupError("existing_keys_required_no_initialization")
    keys = read_json(keys_path, root)
    if any(not isinstance(keys.get(k), str) or not keys[k] for k in
           ("api_token", "bridge_secret", "device_token", "device_secret")):
        raise StartupError("existing_keys_invalid_no_initialization")
    pointer = read_json(root / "run/host-integrator-deploy-pointer.json", root)
    backup = pointer.get("backup")
    if not isinstance(backup, str) or not Path(backup).is_absolute():
        raise StartupError("deployment_backup_path_invalid")
    backup = safe_path(Path(backup), private, directory=True)
    deployment = read_json(backup / "deployment.json", private)
    saved = deployment.get("processes")
    if not isinstance(saved, dict) or set(saved) != {"gateway", "browser"}:
        raise StartupError("saved_external_processes_invalid")
    gateway_script = root / "services/voice/gobot_device_gateway.py"
    browser_script = root.parent / "GoBotHome-host-A/tools/host_a_browser_voice_lab.py"
    config = root / "data/hardware/gobot-v1/gateway.json"
    for path, boundary in ((gateway_script, root), (browser_script, root.parent / "GoBotHome-host-A"),
                           (config, root), (config.parent / "server.pem", root),
                           (config.parent / "server.key", root)):
        safe_path(path, boundary)
    specs = {name: Spec(name, port, (str(python), str(root / "scripts/manage.py"), "worker", name), root)
             for name, port in CORE_PORTS.items()}
    specs["gateway"] = Spec("gateway", 18789,
        (str(python), "-u", str(gateway_script), "--config", str(config)), root)
    specs["browser"] = Spec("browser", 18811, (str(python), "-u", str(browser_script)), root)
    for name in ("gateway", "browser"):
        entry, spec = saved[name], specs[name]
        if (not valid_identity(entry) or entry.get("port") != spec.port
                or not same_path(entry.get("cwd"), root)
                or not same_command(entry.get("cmd"), spec.command)):
            raise StartupError("saved_external_command_not_approved")
    return specs


def owns(process, command, root, owner):
    return (isinstance(process, dict) and same_command(process.get("cmd"), command)
            and same_path(process.get("cwd"), root)
            and str(process.get("owner", "")).casefold() == owner.casefold())


def ancestor(pid, parent, processes):
    """Permit the Windows venv redirector and its exact-command child only."""
    for _ in range(4):
        if pid == parent:
            return True
        item = processes.get(pid)
        if not item:
            return False
        pid = item.get("ppid")
    return False


def inspect(root, specs, snapshot, owner):
    processes, listeners = snapshot["processes"], snapshot["listeners"]
    supervisor_command = (str(root / ".venv/Scripts/python.exe"), str(root / "scripts/manage.py"), "supervise")
    core_path = root / "run/processes.json"
    manifest = read_json(core_path, root) if core_path.exists() else None
    supervisor = None
    if manifest:
        entry = manifest.get("supervisor")
        if not valid_identity(entry) or not isinstance(manifest.get("workers"), dict):
            raise StartupError("core_manifest_invalid")
        observed = processes.get(entry["pid"])
        if same_identity(observed, entry):
            if not (owns(observed, supervisor_command, root, owner) or
                    owns(observed, (*supervisor_command, "adopt"), root, owner)):
                raise StartupError("core_supervisor_identity_mismatch")
            supervisor = entry
    states = {}
    for name, spec in specs.items():
        candidates = {pid: process for pid, process in processes.items()
                      if owns(process, spec.command, root, owner)}
        roots = [pid for pid in candidates if candidates[pid].get("ppid") not in candidates]
        occupied = set(listeners.get(spec.port, ()))
        if any(pid not in candidates for pid in occupied):
            raise StartupError("foreign_or_unverifiable_listener")
        if len(roots) > 1 or len(occupied) > 1:
            raise StartupError("duplicate_owned_processes")
        if name in CORE_PORTS and candidates:
            entry = manifest.get("workers", {}).get(name) if manifest else None
            observed = processes.get(entry.get("pid")) if isinstance(entry, dict) else None
            if (not supervisor or not same_identity(observed, entry)
                    or entry.get("port") != spec.port or observed["pid"] not in candidates
                    or not ancestor(observed["pid"], supervisor["pid"], processes)
                    or any(not ancestor(pid, observed["pid"], processes) for pid in candidates)):
                raise StartupError("core_worker_manifest_identity_mismatch")
        states[name] = "running" if occupied else "starting" if candidates else "stopped"
    # An unrecorded live supervisor may be between spawn and save. Do not start
    # another supervisor, even if it has not bound any port yet.
    supervisors = [p for p in processes.values() if owns(p, supervisor_command, root, owner)
                   or owns(p, (*supervisor_command, "adopt"), root, owner)]
    supervisor_ids = {p["pid"] for p in supervisors}
    if len([p for p in supervisors if p.get("ppid") not in supervisor_ids]) > 1:
        raise StartupError("duplicate_owned_supervisors")
    if supervisors and not supervisor:
        raise StartupError("unrecorded_live_supervisor")
    if supervisor and set(manifest["workers"]) != set(CORE_PORTS):
        raise StartupError("partial_core_manifest")
    state = ("running" if all(v == "running" for v in states.values()) else
             "stopped" if all(v == "stopped" for v in states.values()) and not supervisors else "partial")
    return {"status": state, "services": states, "supervisor": supervisor}


class WindowsSystem:
    def current_owner(self):
        if os.name != "nt":
            raise StartupError("windows_plan_user_required")
        import psutil
        owner = psutil.Process().username()
        if owner.rsplit("\\", 1)[-1].casefold() != "plan":
            raise StartupError("windows_plan_user_required")
        return owner

    def snapshot(self):
        import psutil
        processes = {}
        for p in psutil.process_iter(["pid", "create_time", "cmdline", "cwd", "username", "ppid"], ad_value=None):
            x = p.info
            processes[p.pid] = {"pid": p.pid, "created": x["create_time"], "cmd": x["cmdline"],
                "cwd": x["cwd"], "owner": x["username"], "ppid": x["ppid"]}
        listeners = {}
        for connection in psutil.net_connections(kind="tcp"):
            if connection.status == psutil.CONN_LISTEN and connection.laddr:
                listeners.setdefault(connection.laddr.port, set()).add(connection.pid)
        return {"processes": processes, "listeners": listeners}

    def spawn(self, command, root, label, *, wait=False):
        options = {"creationflags": 0x08000000}  # CREATE_NO_WINDOW; pythonw-safe
        env = os.environ.copy()
        env.update(PYTHONUTF8="1", PYTHONUNBUFFERED="1", PYTHONDONTWRITEBYTECODE="1")
        path = root / "run/sophia-terminal-startup" / (label + ".log")
        if path.exists() or path.is_symlink():
            safe_path(path, root)
        with path.open("ab") as log:
            if wait:
                result = subprocess.run(command, cwd=root, env=env, stdin=subprocess.DEVNULL,
                    stdout=log, stderr=log, timeout=45, **options)
                if result.returncode:
                    raise StartupError("existing_manager_start_failed")
                return None
            child = subprocess.Popen(command, cwd=root, env=env, stdin=subprocess.DEVNULL,
                stdout=log, stderr=log, **options)
        import psutil
        return {"pid": child.pid, "created": psutil.Process(child.pid).create_time()}

    def pause(self):
        time.sleep(.25)


@contextmanager
def launch_lock(root):
    directory = root / "run/sophia-terminal-startup"
    directory.mkdir(exist_ok=True)
    safe_path(directory, root, directory=True)
    path = directory / "start.lock"
    if path.exists():
        safe_path(path, root)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    with os.fdopen(fd, "r+b") as lock:
        if path.stat().st_size == 0:
            lock.write(b"1"); lock.flush()
        lock.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:  # Free mocked tests; production WindowsSystem rejects other OS.
                import fcntl
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise StartupError("startup_already_in_progress") from None
        try:
            yield
        finally:
            lock.seek(0)
            if os.name == "nt":
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def perform(root=ROOT, *, start=False, execute=False, system=None):
    root = Path(root).resolve()
    if start and not execute:
        raise StartupError("start_requires_execute")
    system = system or WindowsSystem()
    owner = system.current_owner()
    if not isinstance(owner, str) or owner.rsplit("\\", 1)[-1].casefold() != "plan":
        raise StartupError("windows_plan_user_required")
    specs = load_specs(root)
    observe = lambda: inspect(root, specs, system.snapshot(), owner)
    before = observe()
    if not start:
        return {**before, "changed": False, "automatic_paid_calls": 0}
    if before["status"] == "running":
        return {**before, "changed": False, "reason": "existing_stack_untouched", "automatic_paid_calls": 0}
    if before["status"] != "stopped":
        raise StartupError("partial_stack_operator_inspection_required")
    with launch_lock(root):
        if observe()["status"] != "stopped":
            raise StartupError("stack_changed_before_start")
        if load_specs(root) != specs:
            raise StartupError("saved_configuration_changed_before_start")
        system.spawn([str(root / ".venv/Scripts/python.exe"), "-X", "utf8",
                      str(root / "scripts/manage.py"), "start"], root, "core-start", wait=True)
        current = observe()
        if any(current["services"][n] != "running" for n in CORE_PORTS):
            raise StartupError("existing_manager_readiness_not_confirmed")
        launched = {}
        for name in ("gateway", "browser"):
            current = observe()
            if current["services"][name] != "stopped":
                raise StartupError("external_process_appeared_during_start")
            launched[name] = system.spawn(list(specs[name].command), root, name)
            for _ in range(160):
                snapshot = system.snapshot()
                child = snapshot["processes"].get(launched[name]["pid"])
                if (not same_identity(child, launched[name]) or
                        not owns(child, specs[name].command, root, owner)):
                    raise StartupError("new_external_process_identity_lost")
                current = inspect(root, specs, snapshot, owner)
                if current["services"][name] == "running":
                    if any(not ancestor(pid, launched[name]["pid"], snapshot["processes"])
                           for pid in snapshot["listeners"].get(specs[name].port, ())):
                        raise StartupError("new_external_listener_identity_mismatch")
                    break
                system.pause()
            else:
                raise StartupError("external_readiness_not_confirmed")
        after = observe()
        if after["status"] != "running":
            raise StartupError("terminal_readiness_not_confirmed")
        # Operational receipt only. Neither this file nor a historical receipt
        # authorizes killing any PID, restoring ledgers or executing free-form argv.
        receipt = {"schema": 1, "updated": time.time(), "supervisor": after["supervisor"],
                   "processes": launched, "automatic_paid_calls": 0}
        path = root / "run/sophia-terminal-startup/processes.json"
        temporary = path.with_suffix(".tmp")
        for existing in (path, temporary):
            if existing.exists() or existing.is_symlink():
                safe_path(existing, root)
        temporary.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
        temporary.replace(path)
        return {**after, "changed": True, "started": list(launched), "automatic_paid_calls": 0}


def parser():
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("command", choices=("status", "start"), nargs="?", default="status")
    value.add_argument("--execute", action="store_true")
    return value


def main():
    args = parser().parse_args()
    try:
        if args.execute and args.command != "start":
            raise StartupError("execute_requires_start")
        result = perform(start=args.command == "start", execute=args.execute)
        exit_code = 0
    except Exception as error:
        result = {"status": "blocked", "reason": str(error) if isinstance(error, StartupError)
                  else "startup_failed_inspect_private_logs", "automatic_retry": False}
        exit_code = 1
    line = json.dumps(result, ensure_ascii=True)
    if sys.stdout is not None:
        print(line, flush=True)
    # pythonw has no console. This writes only a sanitized operational result,
    # and only for an explicitly executed start in an existing private run dir.
    if args.command == "start" and args.execute and (ROOT / "run").is_dir():
        try:
            safe_path(ROOT / "run", ROOT, directory=True)
            path = ROOT / "run/sophia-terminal-startup.log"
            if path.exists() or path.is_symlink():
                safe_path(path, ROOT)
            with path.open("a", encoding="utf-8") as log:
                log.write(line + "\n")
        except (OSError, StartupError):
            pass
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
