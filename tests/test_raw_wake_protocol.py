import base64,importlib.util,zlib
from pathlib import Path
import pytest
FILE=Path(__file__).resolve().parents[1]/'firmware/spotpear/microwake/raw_wake_protocol.py'
spec=importlib.util.spec_from_file_location('raw_protocol',FILE);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
NONCE='a'*32

def begin():
    d=m.Decoder(NONCE,15);d.line(f'GOBOT_RAW_BEGIN {NONCE} 480000 16000 mono_pcm16_pre_afe'.encode());return d

def chunk(seq,data=b'\x00\x01'*480):
    return f'GOBOT_RAW_DATA {NONCE} {seq} {zlib.crc32(data):08x} '.encode()+base64.b64encode(data)

def test_exact_round_trip():
    d=begin()
    for i in range(500):d.line(chunk(i))
    assert not d.done and len(d.pcm)==480000
    d.line(f'GOBOT_RAW_END {NONCE} 500 {zlib.crc32(d.pcm):08x}'.encode());assert d.done
    d.clear();assert not d.pcm

@pytest.mark.parametrize('bad',[
    chunk(1),chunk(0,b'odd'),b'GOBOT_RAW_FAILED',
    f'GOBOT_RAW_END {NONCE} 0 00000000'.encode(),
    chunk(0).replace(b'\x20'+NONCE.encode()+b' ',b' '+b'b'*32+b' '),
    chunk(0).replace(b'000000',b'ffffff'),
])
def test_fail_closed(bad):
    d=begin()
    # Explicit corruption independent of the fixture CRC value.
    if bad==chunk(0):bad=bad[:-1]+b'!'
    with pytest.raises(ValueError):d.line(bad)

def test_duplicate_and_overflow_rejected():
    d=begin();d.line(chunk(0))
    with pytest.raises(ValueError):d.line(chunk(0))
    d=begin()
    for i in range(500):d.line(chunk(i))
    with pytest.raises(ValueError):d.line(chunk(500))
