"""Strict, bounded lossless USB framing. No persistence, logging or network."""
import base64,re,zlib

class Decoder:
    def __init__(self,nonce,seconds):
        if not re.fullmatch('[0-9a-f]{32}',nonce) or not 15<=seconds<=60:raise ValueError('Invalid capture scope')
        self.nonce=nonce;self.limit=seconds*32000;self.pcm=bytearray()
        self.begun=False;self.done=False;self.sequence=0

    def line(self,line):
        if not line.startswith(b'GOBOT_RAW_'):return
        parts=line.decode('ascii').split()
        if parts[0] in {'GOBOT_RAW_ARMED','GOBOT_RAW_STARTED'}:return
        if parts[0]=='GOBOT_RAW_FAILED':raise ValueError('Device capture failed')
        if len(parts)<2 or parts[1]!=self.nonce:raise ValueError('Foreign raw session')
        if parts[0]=='GOBOT_RAW_BEGIN':
            if self.begun or parts!=['GOBOT_RAW_BEGIN',self.nonce,str(self.limit),'16000','mono_pcm16_pre_afe']:
                raise ValueError('Unexpected capture format/size')
            self.begun=True
        elif parts[0]=='GOBOT_RAW_DATA':
            if not self.begun or self.done or len(parts)!=5 or int(parts[2])!=self.sequence:raise ValueError('Missing/repeated chunk')
            data=base64.b64decode(parts[4],validate=True)
            if not data or len(data)>960 or len(data)%2 or zlib.crc32(data)!=int(parts[3],16):raise ValueError('Corrupt PCM chunk')
            if len(self.pcm)+len(data)>self.limit:raise ValueError('Capture exceeds consented duration')
            self.pcm.extend(data);self.sequence+=1
        elif parts[0]=='GOBOT_RAW_END':
            if (not self.begun or self.done or len(parts)!=4 or int(parts[2])!=self.sequence
                or len(self.pcm)!=self.limit or zlib.crc32(self.pcm)!=int(parts[3],16)):
                raise ValueError('Incomplete/corrupt recording')
            self.done=True
        else:raise ValueError('Unknown capture event')

    def clear(self):self.pcm[:]=bytes(len(self.pcm));self.pcm.clear()
