"""Bounded USB status and optional local speaker control. Never print raw UART."""
import argparse
import re
import time

import serial
from serial.tools import list_ports

def observe(seconds, volume=None, sound_check=False, pause_check=False):
    ports = [p for p in list_ports.comports() if (p.vid, p.pid) == (0x303a, 0x1001)]
    if len(ports) != 1:
        raise RuntimeError("Expected exactly one Espressif USB serial port")
    device = serial.Serial(port=None, baudrate=115200, timeout=.15)
    device.port = ports[0].device
    device.dtr = device.rts = False
    device.open()
    deadline = time.monotonic() + seconds
    next_poll = 0
    pending = b""
    with device:
        if volume is not None or sound_check or pause_check:
            # Bind an output change to this enrolled board, exactly as the flash guard does.
            from pathlib import Path
            import json
            import subprocess
            import sys
            device.write(b"\nGOBOT_STATUS\n")
            status_bytes = bytearray()
            until = time.monotonic()+4
            while time.monotonic()<until:
                status_bytes.extend(device.read(4096))
                if re.search(rb"GOBOT_STATUS version=0\.2\.3-dev-touch-auto [^\r\n]*enrolled=1 [^\r\n]*phase=0 ",status_bytes):
                    break
            else:
                raise RuntimeError("Volume control requires an idle, enrolled Spotpear")
            device.close()
            result = subprocess.run([sys.executable,"-m","esptool","--chip","esp32s3",
                                     "--port",ports[0].device,"read-mac"],capture_output=True,timeout=15)
            config = Path(__file__).resolve().parents[2]/"data/hardware/gobot-v1/gateway.json"
            expected = json.loads(config.read_text(encoding="utf8"))["device_mac"].lower()
            if result.returncode or expected not in result.stdout.decode(errors="ignore").lower():
                raise RuntimeError("Enrolled board identity mismatch")
            time.sleep(2)
            device.open()
            # Wait for application readiness after the serial bootloader releases the board.
            boot = bytearray()
            ready_deadline = time.monotonic()+18
            while time.monotonic()<ready_deadline:
                device.write(b"\nGOBOT_STATUS\n")
                boot.extend(device.read(4096))
                if re.search(rb"GOBOT_STATUS version=0\.2\.3-dev-touch-auto [^\r\n]*phase=0 ",boot):
                    break
            else:
                raise RuntimeError("Board is not ready for local sound control")
            if volume is not None:
                device.write(f"\nGOBOT_VOLUME {volume}\n".encode())
            if sound_check:
                device.write(b"\nGOBOT_SOUND_CHECK\n")
            if pause_check:
                device.write(b"\nGOBOT_CHECK_PAUSE\n")
            deadline=time.monotonic()+seconds
        while time.monotonic() < deadline:
            if time.monotonic() >= next_poll:
                device.write(b"\nGOBOT_STATUS\n")
                next_poll = time.monotonic() + 2
            pending += device.read(4096)
            lines = pending.split(b"\n")
            pending = lines.pop()[-8192:]
            for line in lines:
                value = line.decode(errors="replace")
                found = re.search(r"(GOBOT_(?:STATUS version=[\w.-]+(?: \w+=\d+)+|TOUCH_STATUS events=\d+ activations=\d+|ENDPOINT auto_ends=\d+ local=\d+|PAUSE_CHECK armed=1|AUTO_END local=\d+ elapsed_ms=\d+|VOLUME percent=\d+|SOUND_CHECK local=1|LCD atlas=1 size=240x240|ACTIVATION source=(?:touch|button) number=\d+|UTTERANCE_END upload=0)|CST816D not found|Guru Meditation Error|Get chip ID: 0x[\da-fA-F]+)", value)
                if found:
                    print(found[0], flush=True)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=int, default=10, choices=range(1, 301))
    parser.add_argument("--volume", type=int, choices=range(10,101))
    parser.add_argument("--sound-check", action="store_true")
    parser.add_argument("--pause-check", action="store_true")
    args=parser.parse_args()
    observe(args.seconds,args.volume,args.sound_check,args.pause_check)
