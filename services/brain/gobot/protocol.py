"""Firmware wire codec used by test devices only, not a replacement voice server."""
import struct

def pack_opus(payload,version=1,timestamp=0):
    if not payload or len(payload)>65535 or payload.startswith(b'\xff\xd8'):raise ValueError('Opus payload required, never JPEG')
    if version==1:return payload
    if version==2:return struct.pack('>HHIII',2,0,0,timestamp,len(payload))+payload
    if version==3:return struct.pack('>BBH',0,0,len(payload))+payload
    raise ValueError('Unsupported framing version')
def unpack_opus(frame,version):
    if version==1:payload=frame
    elif version==2:
        if len(frame)<16:raise ValueError('Short v2 header')
        v,t,r,ts,n=struct.unpack('>HHIII',frame[:16]);payload=frame[16:]
        if v!=2 or t!=0 or r!=0 or n!=len(payload):raise ValueError('Invalid v2 frame')
    elif version==3:
        if len(frame)<4:raise ValueError('Short v3 header')
        t,r,n=struct.unpack('>BBH',frame[:4]);payload=frame[4:]
        if t!=0 or r!=0 or n!=len(payload):raise ValueError('Invalid v3 frame')
    else:raise ValueError('Unsupported framing version')
    if not payload or len(payload)>65535 or payload.startswith(b'\xff\xd8'):raise ValueError('Invalid audio')
    return payload
