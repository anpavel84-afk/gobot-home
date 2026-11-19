"""Interactive, free-only physical HOST-A acceptance launcher for PLAN.

Do not invoke as a background service. Requires an actual person at COM3 and
an explicit console YES; never flashes, alters NVS/config, records speech to
disk, contacts cloud models, or switches production Brain/B gateway.
Default --preflight only examines files and creates no listener.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import os
import socket
import subprocess
import sys
import time
import uuid

HERE=Path(__file__).resolve().parent
HOSTA=HERE.parent
PLAN=HOSTA.parent/"GoBotHome"
PRIVATE=PLAN/"data"/"hardware"/"gobot-v1"
WORK=HOSTA/"run"/"host-a"


def interpreter(where:Path)->Path:
    path=where.resolve()
    if not path.is_file():
        raise ValueError("missing_installed_local_python")
    return path


def prereqs():
    if not HOSTA.name.endswith("-host-A") or not PLAN.is_dir():
        raise ValueError("expected_existing_PLAN_HOST_A_worktree")
    needed=[
        PRIVATE/"gateway.json",PRIVATE/"server.pem",PRIVATE/"server.key",
        PRIVATE/"irina.onnx",PRIVATE/"irina.onnx.json",
        PLAN/"data"/"models"/"faster-whisper-small"/"model.bin",
        HOSTA/"tools"/"host_rc1_test_listener.py",
        HOSTA/"tools"/"host_rc1_human_usb.py",
    ]
    missing=[p.name for p in needed if not p.is_file()]
    if missing:raise ValueError("missing_local_test_dependency:"+",".join(missing))
    mainpy=interpreter(PLAN/".venv"/"Scripts"/"python.exe")
    com=interpreter(WORK/"rc1-preflight-venv"/"Scripts"/"python.exe")
    from_serial=subprocess.run([str(com),"-c",
        "from serial.tools.list_ports import comports;"
        "p=[x for x in comports() if x.device.upper()=='COM3'];"
        "assert len(p)==1 and p[0].vid==0x303A and p[0].pid==0x1001"],
        check=False,capture_output=True,timeout=5)
    if from_serial.returncode:
        raise ValueError("expected_Spotpear_com3_not_detected")
    if any(p.exists() for p in WORK.glob("host-a-human-*.lock")):
        raise ValueError("previous_trial_lock_exists")
    return mainpy,com


def launch(args):
    mainpy,compy=prereqs()
    print("RC1_HUMAN_PREFLIGHT_PASS: COM3, pinned r3 installed separately",flush=True)
    print("No paid API, Brain, firmware flash, NVS write, audio recording or background service.",flush=True)
    if not args.run:
        print("RC1_HUMAN_DRY_RUN_ONLY. To start, use the local launcher.",flush=True)
        return 0
    if not sys.stdin.isatty():
        raise RuntimeError("only_interactive_console_with_person_at_device")
    answer=input("Вы СЕЙЧАС рядом со Spotpear и согласны на короткий тест микрофона? Напечатайте ДА: ").strip()
    if answer.upper()!="ДА":
        print("RC1_HUMAN_NO_CONSENT_NO_TEST",flush=True);return 4
    session=datetime.now().strftime("%Y%m%dT%H%M%S")+"-"+uuid.uuid4().hex[:6]
    if not WORK.is_dir():raise RuntimeError("private_run_directory_missing")
    flag=WORK/f"host-a-human-{session}.done.json"
    server_report=WORK/f"host-a-human-{session}.server.json"
    person_report=WORK/f"host-a-human-{session}.human.json"
    lock=WORK/f"host-a-human-{session}.lock"
    log=WORK/f"host-a-human-{session}.test-listener.log"
    listener=None
    print("Окно тестирования ограничено; во время него коснитесь GoBot и задайте вопрос о времени.",flush=True)
    try:
        with lock.open("x",encoding="utf8") as private_lock:
            private_lock.write("finite_manual_trial_only")
        listener_cmd=[str(mainpy),"-u",str(HOSTA/"tools"/"host_rc1_test_listener.py"),
                      "--private",str(PRIVATE),"--port","18799","--seconds","195",
                      "--local-time","--report",str(server_report),
                      "--stop-file",str(flag)]
        controller=[str(compy),"-u",str(HOSTA/"tools"/"host_rc1_human_usb.py"),
                    "--port","COM3","--seconds","100","--report",str(person_report),
                    "--prompt-human"]
        with log.open("w",encoding="utf8") as output:
            listener=subprocess.Popen(listener_cmd,stdout=output,stderr=subprocess.STDOUT,
                                      creationflags=subprocess.CREATE_NO_WINDOW,
                                      env={**os.environ,"PYTHONUTF8":"1",
                                           "PYTHONIOENCODING":"utf-8"})
            # Numeric counter logs never contain room audio or transcripts.
            time.sleep(1.5)
            if listener.poll() is not None:
                raise RuntimeError("isolated_host_listener_did_not_start")
            print("HOST_A_TEST_LISTENER_READY (free-only)",flush=True)
            status=subprocess.run(controller,timeout=190,check=False)
            print("HUMAN_USB_RESULT_CODE",status.returncode,flush=True)
            if person_report.is_file():
                receipt=json.loads(person_report.read_text(encoding="utf8"))
                print("HUMAN_CONFIRMATION",json.dumps({
                    "physical_touch_event_delta":receipt.get("physical_touch_event_delta"),
                    "human_heard_audio":receipt.get("human_heard_audio"),
                    "human_saw_display":receipt.get("human_saw_display"),
                    "human_understood_reply":receipt.get("human_understood_reply"),
                    "local_restored":receipt.get("local_restored")},ensure_ascii=False),flush=True)
            if status.returncode:
                return status.returncode
            return 0
    finally:
        flag.write_text(json.dumps({"end":"physical_console_trial_exit",
                                    "no_paid_calls":True,"no_audio_saved":True}),
                        encoding="utf8")
        if listener is not None:
            try:listener.wait(timeout=20)
            except subprocess.TimeoutExpired:
                listener.terminate()
                try:listener.wait(timeout=8)
                except subprocess.TimeoutExpired:listener.kill()
        lock.unlink(missing_ok=True)
        print("HOST_A_CONSOLE_TEST_ENDED. Numeric evidence in ignored run/host-a.",flush=True)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run",action="store_true",help="Requires actual TTY and human physical consent")
    settings=parser.parse_args()
    raise SystemExit(launch(settings))
