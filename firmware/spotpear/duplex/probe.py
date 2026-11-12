"""Bounded local diagnostic on the enrolled, idle S3. Only numeric counters leave UART."""
import argparse
import re
import time
import serial
from serial.tools import list_ports

def observe(seconds,command=None):
    ports=[p for p in list_ports.comports() if(p.vid,p.pid)==(0x303a,0x1001)]
    if len(ports)!=1:raise RuntimeError("One Spotpear USB required")
    dev=serial.Serial(port=None,baudrate=115200,timeout=.15)
    dev.port=ports[0].device;dev.dtr=dev.rts=False;dev.open()
    with dev:
        buf=b"";ready=False
        until=time.monotonic()+4
        while time.monotonic()<until:
            dev.write(b"\nGOBOT_STATUS\n");buf+=dev.read(4096)
            if re.search(rb"GOBOT_STATUS version=0\.4\.[012]-dev-(?:duplex|livekit|session-ack) [^\n]*enrolled=1 [^\n]*phase=0 ",buf):
                ready=True;break
        if command and not ready:raise RuntimeError("Idle enrolled duplex firmware required")
        if command:dev.write(("\n"+command+"\n").encode())
        until=time.monotonic()+seconds;next_poll=0;buf=b""
        while time.monotonic()<until:
            if time.monotonic()>next_poll:dev.write(b"\nGOBOT_STATUS\n");next_poll=time.monotonic()+1
            buf+=dev.read(4096);lines=buf.split(b"\n");buf=lines.pop()[-8192:]
            for raw in lines:
                line=raw.decode(errors="replace")
                found=re.search(r"GOBOT_(?:DUPLEX (?:\w+=\d+ ?)+|DUPLEX_ARMED local=1|SESSION continuous=\d+ phase=\d+|STATUS version=[\w.-]+(?: \w+=\d+)+|MWW (?:\w+=-?\d+ ?)+)|Initialized FD AFE[^\r\n]*|AFE.*(?:failed|Failed)[^\r\n]*|Guru Meditation Error",line)
                if found:print(found[0],flush=True)
                elif any(tag in line for tag in ("esp-tls", "mbedtls", "certificate verify", "GOBOT_STANDBY", "Failed to connect")):
                    safe=re.sub(r"(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}","[device]",line)
                    safe=re.sub(r"(?:https?|wss?)://[^ ]+","[endpoint]",safe)
                    print(safe,flush=True)
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--seconds",type=int,default=15)
    p.add_argument("--media",action="store_true");p.add_argument("--start",action="store_true");p.add_argument("--arm",action="store_true")
    a=p.parse_args()
    if a.media:
        import json
        from pathlib import Path
        config=json.loads(Path("data/hardware/gobot-v1/gateway.json").read_text())
        if config["mode"]!="duplex_test":raise RuntimeError("USB media probe requires the free gateway mode")
    observe(min(60,max(1,a.seconds)),"GOBOT_MEDIA_BEGIN" if a.media else "GOBOT_DUPLEX_BEGIN" if a.start else "GOBOT_DUPLEX_CHECK" if a.arm else None)
