import hashlib,hmac,json,time,secrets,re
from fastapi import HTTPException

def canonical(obj):return json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
def mac(secret,data):return hmac.new(secret.encode(),data,hashlib.sha256).hexdigest()
def signed_request(secret,body):
    nonce=secrets.token_hex(16);stamp=str(int(time.time()))
    return {'X-GoBot-Time':stamp,'X-GoBot-Nonce':nonce,'X-GoBot-Signature':mac(secret,b'POST /v1/stream\n'+stamp.encode()+b'\n'+nonce.encode()+b'\n'+body)}
class Verifier:
    def __init__(self,secret):self.secret=secret;self.seen={}
    def verify(self,headers,body):
        try:
            stamp=headers['x-gobot-time'];nonce=headers['x-gobot-nonce'];sig=headers['x-gobot-signature']
            if abs(time.time()-int(stamp))>15 or not re.fullmatch('[a-f0-9]{32}',nonce):raise ValueError()
            expected=mac(self.secret,b'POST /v1/stream\n'+stamp.encode()+b'\n'+nonce.encode()+b'\n'+body)
            if not hmac.compare_digest(sig,expected):raise ValueError()
            self.seen={k:v for k,v in self.seen.items() if time.time()-v<30}
            if nonce in self.seen or len(self.seen)>1024:raise ValueError()
            self.seen[nonce]=time.time();return nonce
        except (KeyError,ValueError):raise HTTPException(401,'Bridge authentication failed')
def sign_event(secret,nonce,seq,payload):
    obj={'nonce':nonce,'seq':seq,'payload':payload};return {**obj,'signature':mac(secret,canonical(obj))}
def verify_event(secret,nonce,seq,obj):
    signature=obj.get('signature','');unsigned={k:obj[k] for k in ['nonce','seq','payload']}
    if obj['nonce']!=nonce or obj['seq']!=seq or not hmac.compare_digest(signature,mac(secret,canonical(unsigned))):raise ValueError('Bridge response authentication failed')
    return obj['payload']
def redact(text):
    text=re.sub(r'(?i)(bearer\s+)[^\s]+',r'\1[REDACTED]',text)
    text=re.sub(r'(?i)(api[_-]?key|token|password|secret)(\s*[=:]\s*)[^\s,;]+',r'\1\2[REDACTED]',text)
    return re.sub(r'\b(?:sk-|AIza)[A-Za-z0-9_-]{8,}', '[REDACTED]',text)
