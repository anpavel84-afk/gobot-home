"""Patch ONLY a fixed-size model slot locally; verify ESP image integrity.

No filesystem/network/flash operations. A public build template can be compiled
remotely without receiving private weights; callers seal the result with DPAPI.
Unsigned ESP32-S3 app images only. Never patch bootloader or partition images.
"""
import hashlib,struct

def segments(blob):
    if len(blob)<24 or blob[0]!=0xe9 or not 1<=blob[1]<=16 or struct.unpack_from('<H',blob,12)[0]!=9:
        raise ValueError('Expected ESP32-S3 application image')
    if blob[23]!=1:raise ValueError('App must have an appended SHA256 digest')
    cursor=24;parts=[];checksum=0xef
    for _ in range(blob[1]):
        if cursor+8>len(blob):raise ValueError('Truncated segment header')
        addr,size=struct.unpack_from('<II',blob,cursor);start=cursor+8;end=start+size
        if end>len(blob):raise ValueError('Truncated segment data')
        parts.append((addr,start,end))
        for byte in blob[start:end]:checksum^=byte
        cursor=end
    check=(cursor+16)//16*16-1
    if len(blob)!=check+33 or blob[check]!=checksum:raise ValueError('Image checksum/size mismatch')
    if hashlib.sha256(blob[:check+1]).digest()!=blob[check+1:]:raise ValueError('Image digest mismatch')
    return parts,check

def patch(template,placeholder,model,expected_template_sha):
    if hashlib.sha256(template).hexdigest()!=expected_template_sha:raise ValueError('Unexpected public template')
    parts,check=segments(template)
    if not model or len(model)>len(placeholder) or model[4:8]!=b'TFL3':raise ValueError('Invalid/oversized TFLite model')
    if template.count(placeholder)!=1:raise ValueError('Model slot must be unique')
    start=template.index(placeholder);end=start+len(placeholder)
    if not any(a<=start<end<=b for _,a,b in parts):raise ValueError('Model slot crosses segment boundary')
    image=bytearray(template);image[start:end]=model+bytes(len(placeholder)-len(model))
    checksum=0xef
    for _,a,b in parts:
        for byte in image[a:b]:checksum^=byte
    image[check]=checksum;image[check+1:]=hashlib.sha256(image[:check+1]).digest()
    if segments(image)[0]!=parts:raise ValueError('Segment layout changed')
    if image[:start]!=template[:start] or image[end:check]!=template[end:check]:raise ValueError('Non-model payload changed')
    return image
