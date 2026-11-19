"""One-time app-only ESP32-S3 HOST-A RC1 guarded installation.

NEVER write bootloader, partition table, OTA metadata, inactive OTA, NVS,
assets, calibration or raw recording; no paid provider calls. Must be invoked
deliberately with --execute after the read-only preflight. Dry-run default.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time

import serial
from serial.tools import list_ports
from host_rc1_readback_audit import audit, H0_HASH, RC1_HASH

CHIP="esp32s3"
PORT="COM3"
ACTIVE_ADDR="0x20000"
BACKUP_SHA="c7848a7f183fc27340e7872ff8e424fa135eb8a95862a43f5996dd3d4529269b"
APP_BYTES=3047680
MAX_ATTEMPTS=1


def digest(path:Path):
    with path.open("rb") as inp:
        return hashlib.file_digest(inp,"sha256").hexdigest()


def command(*suffix):
    return [sys.executable,"-m","esptool",
            "--chip",CHIP,"--port",PORT,
            "--baud","460800","--connect-attempts","3",
            "--before","default-reset","--after","hard-reset",*suffix]


def run_readonly(argv):
    print("PREFLIGHT_CHECK",argv[-1] if argv else "unknown",flush=True)
    result=subprocess.run(argv,timeout=120,check=False)
    if result.returncode:
        raise RuntimeError("serial_readonly_verification_failed")


def uart_ready():
    identity=[p for p in list_ports.comports() if p.device.upper()==PORT]
    if len(identity)!=1 or identity[0].vid!=0x303A or identity[0].pid!=0x1001:
        raise ValueError("wrong_or_missing_esp32s3_usb_interface")
    # Opening the serial port resets the current XiaoZhi. Wait for Wi-Fi
    # rejoin; emit only status flags, never enroll token or ambient audio.
    with serial.Serial(PORT,baudrate=115200,timeout=.5,
                       write_timeout=2,dsrdtr=False,rtscts=False) as uart:
        uart.dtr=False
        uart.rts=False
        time.sleep(16)
        uart.reset_input_buffer()
        uart.write(b"GOBOT_STATUS\n")
        deadline=time.monotonic()+7
        while time.monotonic()<deadline:
            line=uart.readline().decode("utf8",errors="ignore")
            match=re.search(r"GOBOT_STATUS version=(\S+) wifi=(\d) enrolled=(\d) muted=(\d) phase=(\d).* upload=(\d)",line)
            if match:
                version,wifi,enrolled,muted,phase,upload=match.groups()
                print("BEFORE_FLASH_RUNTIME",version,"wifi="+wifi,
                      "enrolled="+enrolled,"muted="+muted,
                      "phase="+phase,"upload="+upload,flush=True)
                if (version!="0.4.12-dev-guided-calibration-1" or wifi!="1" or
                    enrolled!="1" or muted!="0" or phase!="0" or upload!="0"):
                    raise ValueError("device_not_idle_enrolled_wifi_ready_H0")
                return
    raise ValueError("device_status_not_confirmed")


def preflight(args):
    required=(args.readback,args.h0,args.app)
    if any(not p.is_file() for p in required):
        raise ValueError("missing_image_or_full_private_backup")
    if digest(args.readback)!=BACKUP_SHA or args.readback.stat().st_size!=0x1000000:
        raise ValueError("full_16m_backup_hash_mismatch")
    if digest(args.h0)!=H0_HASH or args.h0.stat().st_size!=3037584:
        raise ValueError("H0_firmware_integrity_failure")
    if digest(args.app)!=RC1_HASH or args.app.stat().st_size!=APP_BYTES:
        raise ValueError("RC1_image_integrity_failure")
    report=audit(args.readback,args.h0,args.app)
    if report["active_slot_selected_from_ota_crc"]!="ota_0" or report["matched_h0_slots"]!=["ota_0"]:
        raise ValueError("H0_not_in_confirmed_active_OTA0")
    if report["otadata_entries"][0]["crc_valid"] is not True:
        raise ValueError("ota_selection_crc_failed")
    if report["partitions"][3]["offset"]!="0x20000":
        raise ValueError("app_partition_offset_changed")
    if args.attempt_marker.exists():
        raise ValueError("only_one_guarded_app_install_per_owner_direct")
    uart_ready()
    # This is a real serial/ROM round trip proving that *this exact preserved*
    # H0 app is present and can be addressed by the recovery tooling.
    run_readonly(command("verify-flash","--flash-size","keep",
                         "--flash-mode","keep","--flash-freq","keep",
                         ACTIVE_ADDR,str(args.h0)))
    return report


def perform(args):
    print("GUARDED_HOST_A_RC1_APP_ONLY_PREFLIGHT_BEGIN",flush=True)
    report=preflight(args)
    print(json.dumps({"preflight":"PASS","chip":"esp32s3",
        "active_slot":"ota_0","address":ACTIVE_ADDR,
        "flash_whitelist":[ACTIVE_ADDR,APP_BYTES],
        "board_rev":"verified_by_esptool",
        "H0_sha256":H0_HASH,"RC1_sha256":RC1_HASH,
        "full_backup_sha256":BACKUP_SHA,
        "non_app_partitions_write_allowed":False,
        "production_gateway_modified":False}),flush=True)
    if not args.execute:
        print("DRY_RUN_ONLY_NO_FLASH_WRITE",flush=True)
        return
    # Exclusive attempt marker BEFORE the sole permitted write. A partial flash
    # must NOT trigger an automatic second attempt. Recovery uses H0 separately.
    args.attempt_marker.parent.mkdir(parents=True,exist_ok=True)
    with args.attempt_marker.open("x",encoding="utf8") as marker:
        marker.write(json.dumps({"status":"attempt_started",
            "rc1_sha256":RC1_HASH,"active_slot":"ota_0",
            "app_only_address":ACTIVE_ADDR}))
    argv=command("write-flash","--flash-size","keep",
                 "--flash-mode","keep","--flash-freq","keep",
                 ACTIVE_ADDR,str(args.app))
    print("APP_ONLY_WRITE_STARTED",flush=True)
    subprocess.run(argv,check=True,timeout=180)
    print("APP_ONLY_WRITE_RETURNED_SUCCESS",flush=True)
    run_readonly(command("verify-flash","--flash-size","keep",
                         "--flash-mode","keep","--flash-freq","keep",
                         ACTIVE_ADDR,str(args.app)))
    print("APP_ONLY_VERIFY_FLASH_PASS",flush=True)


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--readback",type=Path,required=True)
    p.add_argument("--h0",type=Path,required=True)
    p.add_argument("--app",type=Path,required=True)
    p.add_argument("--attempt-marker",type=Path,required=True)
    p.add_argument("--execute",action="store_true")
    x=p.parse_args()
    perform(x)
