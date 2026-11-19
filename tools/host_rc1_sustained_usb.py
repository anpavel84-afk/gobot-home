"""Finite source-hardware HOST-A Wi-Fi sustained-audio soak.

Physical ESP32-S3 must be on PLAN COM3. Touch/voice never synthesized.
No firmware flash, NVS mutation, recording, Brain, B/C/CLI or model calls.
Run simultaneously with separate authenticated HOST test listener.
Both result JSON and stop flag contain counters only, no audio.
"""
from __future__ import annotations
import argparse, json, re, time
from pathlib import Path
import serial
from serial.tools import list_ports

ap=argparse.ArgumentParser()
ap.add_argument("--port",default="COM3")
ap.add_argument("--seconds",type=int,default=300)
ap.add_argument("--marker",type=Path,required=True)
ap.add_argument("--speaker-fixture",action="store_true")
args=ap.parse_args()
if args.port!="COM3" or not 120<=args.seconds<=1820:
    ap.error("bounded_APPROVED_COM3_soak_required")
base=Path(__file__).resolve().parents[1]/"run"/"host-a"
marker=args.marker.resolve()
if base.resolve() not in marker.parents or marker.exists():
    ap.error("private_ignored_unique_marker_required")
matches=[p for p in list_ports.comports() if p.device.upper()=="COM3"]
if len(matches)!=1 or matches[0].vid!=0x303A or matches[0].pid!=0x1001:
    ap.error("esp32s3_USB_identity_not_confirmed")

ready=False;on=False;count_ready=0;wifi=False;status_seen=False
faults=[];start=None;fixture_sent=False;heartbeat_last=0
result={"type":"HOST_RC1_PHYSICAL_WIFI_SOAK","requested_seconds":args.seconds,
        "flash_writes":0,"paid_calls":0,"raw_audio_persisted":False,
        "host_ready":False,"reconnects":0,"local_restored":False,"started":False,
        "completed_seconds":0.0,"success":False}
print("SOAK_HARDWARE_USB_BEGIN",flush=True)
try:
    with serial.Serial(args.port,115200,timeout=.3,write_timeout=1,
                       dsrdtr=False,rtscts=False) as uart:
        uart.dtr=False;uart.rts=False
        time.sleep(16) # opening the port triggers board USB reset
        uart.reset_input_buffer()
        uart.write(b"GOBOT_STATUS\n")
        deadline=time.monotonic()+8
        while time.monotonic()<deadline:
            line=uart.readline().decode("utf8",errors="ignore")
            mat=re.search(r"GOBOT_STATUS version=(\S+) wifi=(\d) enrolled=(\d) muted=(\d) phase=(\d).* upload=(\d)",line)
            if mat:
                v,wifi_s,enroll,muted,phase,upload=mat.groups()
                status_seen=True
                wifi=(v=="0.4.13-dev-host-a-rc1-r3" and
                      wifi_s=="1" and enroll=="1" and muted=="0" and
                      phase=="0" and upload=="0")
                print("SOAK_H0_STATUS",dict(version=v,wifi=int(wifi_s),
                                           enrolled=int(enroll),phase=int(phase),
                                           upload=int(upload)),flush=True)
                break
        if not wifi:raise RuntimeError("fail_safe_wifi_enrollment_idle_precheck")
        try:
            uart.write(b"GOBOT_HOST_ON\n");on=True
            print("SOAK_VOLATILE_HOST_ON",flush=True)
            ready_deadline=time.monotonic()+35
            while True:
                now=time.monotonic()
                if not ready and now>ready_deadline:
                    raise RuntimeError("host_ready_missing_by_deadline")
                if ready and start and now-start>=args.seconds:
                    result["completed_seconds"]=round(now-start,2)
                    result["started"]=True
                    break
                line=uart.readline().decode("utf8",errors="ignore").strip()
                if "GOBOT_STATUS version=" in line:
                    checkpoint=re.search(r"wifi=(\d).*enrolled=(\d).*phase=(\d).*upload=(\d)",line)
                    if checkpoint:
                        wifi_flag,enrolled_flag,phase_flag,upload_flag=checkpoint.groups()
                        if wifi_flag!="1" or enrolled_flag!="1":
                            faults.append("wifi_or_enrollment_lost_during_soak")
                            print("SOAK_STATUS_WIFI_ENROLLMENT_LOST",flush=True)
                        if phase_flag!="0" or upload_flag!="0":
                            faults.append("production_turn_state_during_host_soak")
                            print("SOAK_STATUS_UNEXPECTED_PRODUCTION_TURN",flush=True)
                if "GOBOT_HOST_READY" in line:
                    count_ready+=1
                    if count_ready==1:
                        ready=True;start=time.monotonic();heartbeat_last=start
                        result["host_ready"]=True;result["started"]=True
                        print("SOAK_FIRST_HOST_READY",flush=True)
                    else:
                        result["reconnects"]+=1
                        print("SOAK_RECONNECT_READY",count_ready,flush=True)
                if "GOBOT_HOST_RC1_FAULT" in line or "GOBOT_HOST_TEST_CONNECT_FAILED" in line:
                    faults.append("host_fault_or_reconnect")
                    print("SOAK_REPORTED_HOST_FAULT",flush=True)
                if line and "GOBOT_HOST_MODE" in line:
                    print("SOAK_HOST_MODE_ACK",line[line.index("GOBOT_HOST_MODE"):][:80],flush=True)
                if ready and start:
                    if args.speaker_fixture and not fixture_sent and now-start>=5:
                        uart.write(b"GOBOT_HOST_TONE\n")
                        fixture_sent=True
                        print("SOAK_FREE_FIXTURE_REQUESTED",flush=True)
                    if now-heartbeat_last>=60:
                        heartbeat_last=now
                        elapsed=round(now-start,2)
                        result["completed_seconds"]=elapsed
                        uart.write(b"GOBOT_STATUS\n")
                        print("SOAK_MONOTONIC_PROGRESS",elapsed,flush=True)
        finally:
            if on:
                uart.write(b"GOBOT_HOST_OFF\n")
                print("SOAK_VOLATILE_HOST_OFF_SENT",flush=True)
                until=time.monotonic()+7
                while time.monotonic()<until:
                    line=uart.readline().decode("utf8",errors="ignore")
                    if "GOBOT_HOST_MODE OFF" in line:
                        result["local_restored"]=True
                        print("SOAK_LOCAL_MODE_RESTORED",flush=True)
                        break
    result["reconnects"]=max(0,count_ready-1)
    result["fault_count"]=len(faults)
    result["success"]=(result["host_ready"] and result["local_restored"]
                       and result["completed_seconds"]>=args.seconds
                       and result["reconnects"]==0 and not faults)
except Exception as exc:
    result["blocked_or_failed"]=type(exc).__name__+":"+str(exc)
    print("SOAK_FAILURE_CLASS",result["blocked_or_failed"],flush=True)
finally:
    marker.parent.mkdir(parents=True,exist_ok=True)
    marker.write_text(json.dumps(result,indent=2),encoding="utf8")
    print("SOAK_HARDWARE_USB_RESULT",json.dumps(result),flush=True)
if not result["success"]:
    raise SystemExit(10)
