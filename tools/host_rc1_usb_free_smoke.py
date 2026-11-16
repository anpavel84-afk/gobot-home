"""Single finite physical Spotpear/PLAN free audio smoke via COM3.

Opens serial once, waits for device's Wi-Fi, enables volatile HOST, requests a
non-AI local tone after HOST readiness, and returns to LOCAL. No flash, no NVS,
no audio recording and no paid B/C/CLI or Brain calls.
"""
from __future__ import annotations
import argparse,re,time
import serial

P=argparse.ArgumentParser()
P.add_argument("--port",default="COM3")
P.add_argument("--active-seconds",type=int,default=65)
P.add_argument("--mic-only",action="store_true")
args=P.parse_args()
if args.port!="COM3" or not 20<=args.active_seconds<=180:
    P.error("bounded_approved_serial_test_required")
start=time.monotonic()
ready=False;on=False;tone_sent=False;host_first_ready=None;wifi_ok=False
print("HOST_RC1_PHYSICAL_USB_TEST_START",flush=True)
with serial.Serial("COM3",115200,timeout=.3,write_timeout=1,
                   dsrdtr=False,rtscts=False) as uart:
    uart.dtr=False;uart.rts=False
    time.sleep(16)
    uart.reset_input_buffer()
    uart.write(b"GOBOT_STATUS\n")
    until=time.monotonic()+7
    while time.monotonic()<until:
        line=uart.readline().decode("utf8",errors="ignore")
        if "GOBOT_STATUS version=" in line:
            match=re.search(r"version=(\S+).*wifi=(\d).*enrolled=(\d).*phase=(\d).*upload=(\d)",line)
            if match:
                version,wifi,enrolled,phase,upload=match.groups()
                wifi_ok=(version=="0.4.13-dev-host-a-rc1-r3" and
                         wifi=="1" and enrolled=="1" and phase=="0" and upload=="0")
                print("HOST_RC1_BEFORE_TEST",version,
                      "wifi="+wifi,"enrolled="+enrolled,
                      "phase="+phase,"upload="+upload,flush=True)
                break
    if wifi_ok:
        uart.write(b"GOBOT_HOST_ON\n");on=True
        print("HOST_RC1_VOLATILE_HOST_ON_SENT",flush=True)
        begin=time.monotonic()
        while time.monotonic()<begin+args.active_seconds:
            line=uart.readline().decode("utf8",errors="ignore").strip()
            if "GOBOT_HOST_" in line:
                event=line[line.index("GOBOT_HOST_"):].splitlines()[0][:200]
                event=re.sub(r"(?i)(token|password|key|mac)=[^\s]+",r"\1=[redacted]",event)
                print("HOST_RC1_UART",event,flush=True)
                if "GOBOT_HOST_READY" in line:
                    ready=True
                    host_first_ready=time.monotonic()
            if ready and not args.mic_only and not tone_sent and host_first_ready is not None and time.monotonic()-host_first_ready>=6:
                uart.write(b"GOBOT_HOST_TONE\n")
                tone_sent=True
                print("HOST_RC1_FREE_TONE_REQUESTED",flush=True)
    else:
        print("HOST_RC1_BLOCKED_NOT_ENROLLED_OR_NO_WIFI",flush=True)
    if on:
        uart.write(b"GOBOT_HOST_OFF\n")
        print("HOST_RC1_VOLATILE_HOST_OFF_SENT",flush=True)
        end=time.monotonic()+4
        while time.monotonic()<end:
            line=uart.readline().decode("utf8",errors="ignore")
            if "GOBOT_HOST_MODE OFF" in line:
                print("HOST_RC1_LOCAL_MODE_RESTORED",flush=True)
                break
print("HOST_RC1_RESULT",dict(host_ready=ready,tone_requested=tone_sent,
                              wifi_preflight=wifi_ok,flash_writes=0,
                              paid_calls=0,audio_saved=False),flush=True)
if not ready or (not args.mic_only and not tone_sent):raise SystemExit(6)
