import hashlib,importlib.util,struct
from pathlib import Path
import pytest
FILE=Path(__file__).resolve().parents[1]/'firmware/spotpear/microwake/private_image.py'
spec=importlib.util.spec_from_file_location('wake_private_image',FILE);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def image(payload):
    header=bytearray(24);header[0]=0xe9;header[1]=1;header[23]=1;struct.pack_into('<H',header,12,9)
    data=header+struct.pack('<II',0x3c000020,len(payload))+payload
    while len(data)%16!=15:data.append(0)
    checksum=0xef
    for v in payload:checksum^=v
    data.append(checksum);return bytes(data)+hashlib.sha256(data).digest()

def test_only_model_slot_and_integrity_change():
    slot=b'public-model'+bytes(100);before=image(b'prefix'+slot+b'suffix');model=b'1234TFL3private'
    after=m.patch(before,slot,model,hashlib.sha256(before).hexdigest())
    assert len(after)==len(before) and m.segments(after)[0]==m.segments(before)[0]
    assert b'prefix'+model in after and b'suffix' in after

@pytest.mark.parametrize('failure',['hash','digest','duplicate','oversize'])
def test_malformed_or_ambiguous_image_refused(failure):
    slot=b'public-model'+bytes(100);before=image(slot if failure!='duplicate' else slot+slot);sha=hashlib.sha256(before).hexdigest();model=b'1234TFL3private'
    if failure=='hash':sha='0'*64
    if failure=='digest':before=before[:-1]+bytes([before[-1]^1]);sha=hashlib.sha256(before).hexdigest()
    if failure=='oversize':model=b'1234TFL3'+bytes(1000)
    with pytest.raises(ValueError):m.patch(before,slot,model,sha)
