"""One-shot manual/physical-touch HOST-A RC1 acceptance controller for PLAN.

**Only run while physically next to the Spotpear.** Uses existing installed
r3 firmware and private LAN listener, never flashes or persists NVS, never
records speech to disk or invokes paid Brain/B/C/CLI. No fake touch or wake.
Guaranteed best-effort GOBOT_HOST_OFF even after test errors/interrupt.
"""
from __future__ import annotations
import argparse, json, re, time, traceback
from pathlib import Path
import serial
from serial.tools import list_ports

DEFAULT_SECONDS=100
PORT="COM3"
STATUS=re.compile(
    r"GOBOT_STATUS version=(\S+) wifi=(\d) enrolled=(\d) muted=(\d) phase=(\d).* upload=(\d)"
)
TOUCH=re.compile(r"GOBOT_TOUCH_STATUS events=(\d+) activations=(\d+)")

def parse_args():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port",default=PORT)
    ap.add_argument("--seconds",type=int,default=DEFAULT_SECONDS)
    ap.add_argument("--report",required=True,type=Path)
    ap.add_argument("--prompt-human",action="store_true")
    opt=ap.parse_args()
    if opt.port!=PORT or not 40<=opt.seconds<=180:
        ap.error("approved_PORT_COM3_and_40_to_180_second_trial_required")
    private=Path(__file__).resolve().parents[1]/"run"/"host-a"
    if private.resolve() not in opt.report.resolve().parents or opt.report.exists():
        ap.error("private_new_report_path_required")
    board=[p for p in list_ports.comports() if p.device.upper()==PORT]
    if len(board)!=1 or board[0].vid!=0x303A or board[0].pid!=0x1001:
        ap.error("expected_existing_ESP32S3_USB_not_found")
    return opt

def run(opt):
    report={
        "kind":"HOST_A_RC1_PHYSICAL_HUMAN_CONSOLE_TRIAL",
        "firmware":"0.4.13-dev-host-a-rc1-r3",
        "flash_writes":0,"paid_calls":0,"recording_saved":False,
        "usb_ready":False,"host_ready":False,"local_restored":False,
        "physical_touch_event_delta":None,
        "manual_status_only":True,
        "human_heard_audio":"not_reported",
        "human_saw_display":"not_reported",
        "human_understood_reply":"not_reported",
        "human_confirmed":False
    }
    switched=False
    prior_touches=None;last_touches=None
    print("BEGIN_OWNER_ASSISTED_PHYSICAL_TOUCH; no room recording.",flush=True)
    try:
        with serial.Serial(PORT,115200,timeout=.3,write_timeout=1,
                           dsrdtr=False,rtscts=False) as uart:
            uart.dtr=False;uart.rts=False
            time.sleep(16)
            uart.reset_input_buffer()
            uart.write(b"GOBOT_STATUS\n")
            deadline=time.monotonic()+8
            baseline_status=False
            while time.monotonic()<deadline:
                line=uart.readline().decode("utf8",errors="ignore")
                m=STATUS.search(line)
                if m:
                    ver,wifi,enrolled,muted,phase,upload=m.groups()
                    baseline_status=(ver==report["firmware"] and wifi=="1" and
                                     enrolled=="1" and muted=="0" and phase=="0" and upload=="0")
                    print("PHYSICAL_PRECHECK",json.dumps({
                        "firmware":ver,"wifi":wifi,"enrolled":enrolled,
                        "muted":muted,"phase":phase,"upload":upload}),flush=True)
                    break
            if not baseline_status:raise RuntimeError("HARDWARE_NOT_READY")
            report["usb_ready"]=True
            uart.write(b"GOBOT_HOST_ON\n");switched=True
            wait_ready=time.monotonic()+35
            while time.monotonic()<wait_ready:
                line=uart.readline().decode("utf8",errors="ignore")
                if "GOBOT_HOST_READY" in line:
                    report["host_ready"]=True
                    print("HOST_READY_PHYSICAL_TOUCH_MANUAL_TEST_NOW",flush=True)
                    break
            if not report["host_ready"]:raise RuntimeError("HOST_READY_NOT_SEEN")
            uart.write(b"GOBOT_STATUS\n")
            baseline_until=time.monotonic()+5
            while time.monotonic()<baseline_until:
                baseline_line=uart.readline().decode("utf8",errors="ignore")
                first=TOUCH.search(baseline_line)
                if first:
                    prior_touches=last_touches=int(first.group(1))
                    print("PHYSICAL_TOUCH_BASELINE",prior_touches,flush=True)
                    break
            if prior_touches is None:
                raise RuntimeError("touch_baseline_unavailable")
            print("КОСНИТЕСЬ ЭКРАНА ГОБОТА ОДИН РАЗ И СКАЖИТЕ: «Скажи, сколько сейчас времени?»",flush=True)
            stop_at=time.monotonic()+opt.seconds
            last_status=0.0
            while time.monotonic()<stop_at:
                now=time.monotonic()
                if now-last_status>12:
                    last_status=now
                    uart.write(b"GOBOT_STATUS\n")
                line=uart.readline().decode("utf8",errors="ignore")
                m=TOUCH.search(line)
                if m:
                    last_touches=int(m.group(1))
                    if prior_touches is None:
                        prior_touches=last_touches
                    print("PHYSICAL_TOUCH_COUNTER",last_touches,flush=True)
                if "GOBOT_HOST_RC1_FAULT" in line:
                    raise RuntimeError("DEVICE_HOST_RC1_FAULT")
            if prior_touches is not None and last_touches is not None:
                report["physical_touch_event_delta"]=max(0,last_touches-prior_touches)
    except Exception as e:
        report["failure_code"]=type(e).__name__+":"+str(e)
        print("PHYSICAL_TRIAL_FAILURE",type(e).__name__,flush=True)
    finally:
        # This is the controlling safety action. Never leave HOST streaming if
        # the local console exits on a Python exception.
        try:
            if switched:
                with serial.Serial(PORT,115200,timeout=.3,write_timeout=1,
                                   dsrdtr=False,rtscts=False) as uart:
                    uart.dtr=False;uart.rts=False
                    # Reopening COM3 resets r3; it defaults LOCAL, but wait for
                    # the actual firmware boot before sending/verifying OFF.
                    time.sleep(16)
                    uart.reset_input_buffer()
                    uart.write(b"GOBOT_HOST_OFF\n")
                    end=time.monotonic()+7
                    while time.monotonic()<end:
                        line=uart.readline().decode("utf8",errors="ignore")
                        if "GOBOT_HOST_MODE OFF" in line:
                            report["local_restored"]=True
                            print("PHYSICAL_LOCAL_RESTORED",flush=True)
                            break
        except Exception as e:
            report["local_restore_error"]=type(e).__name__
    # If the normal firmware already reset on USB reopen, it defaults LOCAL;
    # verify separately by GOBOT_STATUS before any acceptance.
    if opt.prompt_human and report["host_ready"] and report["local_restored"]:
        print("Ответьте только по факту физических наблюдений (да/нет/не знаю).",flush=True)
        for key,label in (
            ("human_heard_audio","Была слышна речь из динамика?"),
            ("human_saw_display","Экран менял стадии listening/thinking/speaking?"),
            ("human_understood_reply","Ответ про время был понятен?")
        ):
            ans=input(label+" ").strip().lower()
            if ans in ("да","нет","не знаю"):
                report[key]=ans
        report["human_confirmed"]=True
    opt.report.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf8")
    print("PHYSICAL_HUMAN_ACCEPTANCE_CONSOLE_REPORT",json.dumps(
        report,ensure_ascii=True),flush=True)
    if not report["host_ready"] or not report["local_restored"]:
        return 3
    return 0

if __name__=="__main__":
    raise SystemExit(run(parse_args()))
