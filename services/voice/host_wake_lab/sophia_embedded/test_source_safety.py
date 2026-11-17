"""Public source safety checks; private official model weights are optional.

On authorized private builder, validates the exact model binary if present.
Without local weights, the checks still verify published source/gating policy.
Never connects to a microphone, hardware, network, API or serial port.
"""
from pathlib import Path
import hashlib

ROOT=Path(__file__).resolve().parent
MODEL=ROOT/"main"/"sophia_srmodels.bin"
EXPECTED="f3aaf5c6017dc7460e8acd58e2204b85692747b9b5d42e6a54ee831d9fdad415"
if MODEL.is_file():
    assert MODEL.stat().st_size==383508
    assert hashlib.sha256(MODEL.read_bytes()).hexdigest()==EXPECTED
    b=MODEL.read_bytes()[:16]
    assert b[:4]==b"\x01\x00\x00\x00" and b[4:15]==b"wn10_sophia"
    print("PRIVATE_OFFICIAL_SOPHIA_MODEL_SHA256_AND_HEADER_PASS")
else:
    print("PRIVATE_SOPHIA_MODEL_NOT_COMMITTED_EXPECTED")

src=(ROOT/"main"/"embedded_sophia_engine.hpp").read_text(encoding="utf-8")
assert "srmodel_load(sophia_embedded_start)" in src
assert 'std::memcmp(sophia_embedded_start+4,"wn10_sophia",11)' in src
assert "ingest_existing_pcm" in src
assert "i2s_driver_install" not in src.lower()
assert "erase_flash" not in src.lower()
table=(ROOT/"partitions_RC1_LAYOUT_CHECK_ONLY.csv").read_text(encoding="utf-8")
assert not any(line.lower().startswith("model,") for line in table.splitlines())
for row in ("ota_0, app, ota_0, 0x20000, 0x3f0000",
            "ota_1, app, ota_1, 0x410000, 0x3f0000",
            "assets, data, 0x82, 0x800000, 0x800000"):
    assert row in table
assert 'EMBED_FILES "sophia_srmodels.bin"' in (ROOT/"main"/"CMakeLists.txt").read_text(encoding="utf-8")
assert "WN10_SOPHIA=y" in (ROOT/"sdkconfig.defaults").read_text()
assert "NOT_PROVEN" in (ROOT/"BUILD_REPORT.md").read_text(encoding="utf-8")
print("SOPHIA_EMBEDDED_SOURCE_GUARDS_PASS")