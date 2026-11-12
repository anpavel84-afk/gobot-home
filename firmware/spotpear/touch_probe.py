"""Read-only, bounded USB observation for the enrolled board. Never print raw UART."""
import argparse
import re
import time

import serial
from serial.tools import list_ports

def observe(seconds):
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
        while time.monotonic() < deadline:
            if time.monotonic() >= next_poll:
                device.write(b"\nGOBOT_STATUS\n")
                next_poll = time.monotonic() + 2
            pending += device.read(4096)
            lines = pending.split(b"\n")
            pending = lines.pop()[-8192:]
            for line in lines:
                value = line.decode(errors="replace")
                found = re.search(r"(GOBOT_(?:STATUS version=[\w.-]+(?: \w+=\d+)+|TOUCH_STATUS events=\d+ activations=\d+|LCD atlas=1 size=240x240|ACTIVATION source=(?:touch|button) number=\d+|UTTERANCE_END upload=0)|CST816D not found|Guru Meditation Error|Get chip ID: 0x[\da-fA-F]+)", value)
                if found:
                    print(found[0], flush=True)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=int, default=10, choices=range(1, 301))
    observe(parser.parse_args().seconds)
