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
            if re.search(rb"GOBOT_STATUS version=0\.4\.[01]-dev-(?:duplex|livekit) [^\n]*enrolled=1 [^\n]*phase=0 ",buf):
                ready=True;break
        if command and not ready:raise RuntimeError("Idle enrolled duplex firmware required")
        if command:dev.write(("\n"+command+"\n").encode())
        until=time.monotonic()+seconds;next_poll=0;buf=b""
        while time.monotonic()<until:
            if time.monotonic()>next_poll:dev.write(b"\nGOBOT_STATUS\n");next_poll=time.monotonic()+1
            buf+=dev.read(4096);lines=buf.split(b"\n");buf=lines.pop()[-8192:]
            for raw in lines:
                line=raw.decode(errors="replace")
                found=re.search(r"GOBOT_(?:DUPLEX (?:\w+=\d+ ?)+|DUPLEX_ARMED local=1|STATUS version=[\w.-]+(?: \w+=\d+)+|MWW (?:\w+=-?\d+ ?)+)|Initialized FD AFE[^\r\n]*|AFE.*(?:failed|Failed)[^\r\n]*|Guru Meditation Error",line)
                if found:print(found[0],flush=True)
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--seconds",type=int,default=15)
    p.add_argument("--start",action="store_true");p.add_argument("--arm",action="store_true")
    a=p.parse_args()
    observe(min(60,max(1,a.seconds)),"GOBOT_DUPLEX_BEGIN" if a.start else "GOBOT_DUPLEX_CHECK" if a.arm else None)
