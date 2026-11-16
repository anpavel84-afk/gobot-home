"""Read-only USB status preflight. No NVS changes, flash operations, audio capture."""
import argparse
import re
import time

import serial

parser=argparse.ArgumentParser()
parser.add_argument('--port',default='COM3')
parser.add_argument('--seconds',type=float,default=6)
parser.add_argument('--settle',type=float,default=0)
args=parser.parse_args()
if args.port!='COM3' or not 1<=args.seconds<=10 or not 0<=args.settle<=30:
    parser.error('approved_port_and_bounded_interval_required')
print('HOST_RC1_USB_STATUS_BEGIN',flush=True)
count=0
try:
    with serial.Serial(port=args.port,baudrate=115200,timeout=.25,
                       write_timeout=1,dsrdtr=False,rtscts=False) as uart:
        uart.dtr=False
        uart.rts=False
        time.sleep(.2+args.settle)
        uart.reset_input_buffer()
        uart.write(b'GOBOT_STATUS\n')
        deadline=time.monotonic()+args.seconds
        while time.monotonic()<deadline:
            line=uart.readline().decode('utf-8',errors='ignore')
            if re.search(r'GOBOT_(STATUS|ENDPOINT|TOUCH_STATUS|STANDBY)\b',line):
                # Published evidence must not contain device identifier or secret.
                piece=line[line.find('GOBOT_'):].strip()[:350]
                piece=re.sub(r'(?i)(token|key|secret|password|mac)=\S+',r'\1=[redacted]',piece)
                print(piece,flush=True)
                count+=1
except serial.SerialException as error:
    print('HOST_RC1_USB_BLOCKED',type(error).__name__,flush=True)
    raise
print('HOST_RC1_USB_STATUS_COUNT',count,flush=True)
