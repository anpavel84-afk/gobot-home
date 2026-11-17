"""HOST-B read-only PLAN prerequisites for future A-owned Sophia hardware acceptance.

No USB/COM3, device I/O, network, model inference, firmware edits or writes.
Verifies official model and the originally preserved H0/RC1 binary backups.
Does NOT authorize or implement any installation. No user audio is processed.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import struct

EXPECTED = {
    "official_sophia_packed": (383508, "f3aaf5c6017dc7460e8acd58e2204b85692747b9b5d42e6a54ee831d9fdad415"),
    "sophia_rc1_diag_v2": (3667024, "53b6521146cde1f64e6499d46ba9315218eacb808d6e8ea5208c66faa8187462"),
    "installed_rc1_r3_app": (3047680, "5186b41a80d3f4155dd544fa1112975eca74fa4b979d62c275b6804626d13576"),
    "preserved_h0_full": (16777216, "c7848a7f183fc27340e7872ff8e424fa135eb8a95862a43f5996dd3d4529269b"),
    "preserved_postflash_full": (16777216, "98bcfdff4c9fa1e4092966336e246695a5112a17aa95c206dbfbf9eec3d31486"),
}

PARTITIONS = {
    "nvs": (0x9000, 0x4000),
    "otadata": (0xD000, 0x2000),
    "phy_init": (0xF000, 0x1000),
    "ota_0": (0x20000, 0x3F0000),
    "ota_1": (0x410000, 0x3F0000),
    "assets": (0x800000, 0x800000),
}

def verified_bytes(label: str, path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label}: missing_or_symlink")
    length, digest = EXPECTED[label]
    value = path.read_bytes()
    if len(value) != length or hashlib.sha256(value).hexdigest() != digest:
        raise ValueError(f"{label}: SHA256_or_length_not_matching_documented_checkpoint")
    return value

def partition_map(flash_image: bytes) -> dict[str, tuple[int, int]]:
    table=flash_image[0x8000:0x9000]
    entries={}
    for offset in range(0,len(table),32):
        chunk=table[offset:offset+32]
        magic=int.from_bytes(chunk[:2],"little")
        if magic in (0xFFFF,0xEBEB):
            break
        if magic!=0x50AA:
            raise ValueError(f"partition_magic_invalid_at_{offset}")
        _,typ,subtype,start,length,name,flags=struct.unpack("<HBBII16sI",chunk)
        label=name.partition(b"\x00")[0].decode("ascii")
        if not label or label in entries:
            raise ValueError("duplicate_or_unnamed_partition")
        entries[label]=(start,length)
    return entries

def main() -> None:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--model",required=True,type=Path)
    p.add_argument("--rc1",required=True,type=Path)
    p.add_argument("--h0",required=True,type=Path)
    p.add_argument("--post",required=True,type=Path)
    p.add_argument("--diagnostic-app",type=Path,default=None)
    args=p.parse_args()

    model=verified_bytes("official_sophia_packed",args.model)
    if model[:4]!=b"\x01\x00\x00\x00" or model[4:15]!=b"wn10_sophia":
        raise ValueError("model_header_not_official_sophia")
    verified_bytes("installed_rc1_r3_app",args.rc1)
    h0=verified_bytes("preserved_h0_full",args.h0)
    post=verified_bytes("preserved_postflash_full",args.post)
    before=partition_map(h0)
    after=partition_map(post)
    if before!=after:
        raise ValueError("pre_and_post_partition_layout_differ")
    for name,expected in PARTITIONS.items():
        if before.get(name)!=expected:
            raise ValueError(f"unexpected_partition_{name}")
    if "model" in before:
        raise ValueError("observed_layout_incorrectly_has_model_partition")
    candidate_ok=False
    if args.diagnostic_app is not None:
        candidate=verified_bytes("sophia_rc1_diag_v2",args.diagnostic_app)
        if candidate.count(model)!=1:
            raise ValueError("verified_candidate_model_not_embedded_exactly_once")
        for marker in (b"0.4.13-dev-host-b-sophia-diagnostic-NOT-FOR-FLASH",
                       b"SOPHIA_DIAG_MEMORY",b"SOPHIA_LOCAL_DETECTED",
                       b"GOBOT_SOPHIA_TEST_ON",b"GOBOT_SOPHIA_TEST_OFF"):
            if marker not in candidate:
                raise ValueError("candidate_missing_diagnostic_guard:"+str(marker))
        candidate_ok=True
    if h0[0x8000:0x9000]!=post[0x8000:0x9000]:
        raise ValueError("partition_table_bytes_changed")
    # This preflight does NOT attest bitwise NVS equality; prior boot changed
    # sectors 0xA000..0xC000, which MUST remain a separately documented caveat.
    print(json.dumps({
        "status":"READ_ONLY_BACKUP_AND_SOPHIA_MODEL_CHECK_PASS",
        "offline_sophia_weight_bytes":len(model),
        "official_model_name":"wn10_sophia",
        "candidate_diagnostic_app_hash_verified":candidate_ok,
        "candidate_embeds_one_exact_model":candidate_ok,
        "candidate_official_version_marker_NOT_FOR_FLASH":candidate_ok,
        "rc1_r3_app_hash_verified":True,
        "full_h0_image_hash_verified":True,
        "full_postflash_image_hash_verified":True,
        "partition_table_same_between_backups":True,
        "model_partition_on_installed_layout":False,
        "existing_ota0_size_bytes":before["ota_0"][1],
        "original_asset_partition_size_bytes":before["assets"][1],
        "NVS_bitwise_unchanged":False,
        "current_live_board_state":"NOT_QUERIED",
        "current_software_host_a_wip":"NOT_PATCHED",
        "rc1_derived_diagnostic_app_built":candidate_ok,
        "full_rc1_sophia_production_firmware_built":False,
        "flash_safe":False,
        "flash_authorized_by_this_preflight":False,
        "HOST_A_exclusive_hardware_install_review_complete":False,
        "radio_device_or_COM3_touched":False,
        "paid_calls":0,
    },ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
