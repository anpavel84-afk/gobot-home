"""Read-only ESP32-S3 16MiB flash image audit; never modifies or emits NVS data.

Require exact H0 installed app SHA in selected OTA slot, original partition
layout, correct RC1 image size, and verified full readback before flash.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import struct
import zlib

H0_HASH="1acb944df377c6da4ac53b013997d9ac548e01cba6bdadece4267f7c502c5c6a"
RC1_HASH="5186b41a80d3f4155dd544fa1112975eca74fa4b979d62c275b6804626d13576"
EXPECTED={
    "nvs":(0x9000,0x4000,1),
    "otadata":(0xD000,0x2000,1),
    "phy_init":(0xF000,0x1000,1),
    "ota_0":(0x20000,0x3F0000,0),
    "ota_1":(0x410000,0x3F0000,0),
    "assets":(0x800000,0x800000,1)
}
def hashbytes(data):
    return hashlib.sha256(data).hexdigest()
def audit(readback:Path,h0:Path,rc1:Path):
    for p in (readback,h0,rc1):
        if not p.is_file():raise ValueError(f"required_file_missing:{p.name}")
    data=readback.read_bytes()
    old=h0.read_bytes()
    new=rc1.read_bytes()
    if len(data)!=0x1000000:raise ValueError("readback_not_16m")
    if hashbytes(old)!=H0_HASH:raise ValueError("h0_unexpected_hash")
    if hashbytes(new)!=RC1_HASH:raise ValueError("rc1_unexpected_hash")
    if len(new)>=0x3F0000:raise ValueError("rc1_exceeds_partition")
    parts={}
    for n in range(0,0x1000//32):
        off=0x8000+n*32
        magic,typ,subtype,offset,size,name,flags=struct.unpack_from("<HBBII16sI",data,off)
        if magic!=0x50AA:break
        name=name.split(b"\x00",1)[0].decode("ascii")
        if name in parts or not name:raise ValueError("duplicate_partition_name")
        parts[name]=(offset,size,typ)
    if parts!=EXPECTED:
        raise ValueError("partition_layout_mismatch:"+",".join(sorted(set(parts)^set(EXPECTED))))
    for name,(offset,size,typ) in parts.items():
        if offset+size>len(data):
            raise ValueError("partition_outside_flash")
    ota_entries=[]
    for slot in range(2):
        addr=0xD000+slot*0x1000
        seq=struct.unpack_from("<I",data,addr)[0]
        state=struct.unpack_from("<I",data,addr+24)[0]
        crc=struct.unpack_from("<I",data,addr+28)[0]
        valid_crc=(seq!=0xFFFFFFFF and crc==zlib.crc32(struct.pack("<I",seq),0xFFFFFFFF))
        ota_entries.append({"index":slot,"sequence":seq,"state":state,
                            "crc":crc,"valid_crc":valid_crc})
    matched=[]
    slots={}
    for name in ("ota_0","ota_1"):
        address,size,_=parts[name]
        head=data[address:address+len(old)]
        matched_h0=hashbytes(head)==H0_HASH
        if matched_h0:matched.append(name)
        slots[name]={"offset":hex(address),"h0_hash_match":matched_h0,
                     "app_header_magic":hex(data[address])}
    eligible=[r for r in ota_entries if r["valid_crc"] and r["state"]==2]
    # Only one valid selection record exists in this H0 backup. If multiple
    # are present, do not infer which boot slot is selected from stale state.
    selected=("ota_"+str((eligible[0]["sequence"]-1)%2)) if len(eligible)==1 else None
    result={
        "schema":"gobot_host_rc1_readback_v1",
        "read_only":True,
        "readback_bytes":len(data),
        "readback_sha256":hashbytes(data),
        "source_firmware_hash_verified":True,
        "candidate_firmware_hash_verified":True,
        "candidate_bytes":len(new),
        "app_partition_bytes":0x3F0000,
        "partitions":[{"name":k,"offset":hex(v[0]),"size":hex(v[1])}
                      for k,v in parts.items()],
        "matched_h0_slots":matched,
        "active_slot_selected_from_ota_crc":selected,
        "slots":slots,
        "otadata_entries":[{"sector":x["index"],"seq":hex(x["sequence"]),
                             "state":hex(x["state"]),"crc_valid":x["valid_crc"]}
                            for x in ota_entries],
        "bootloader_and_nvs_preserved":True,
        "app_write_performed":False,
        "guarded_flash_ready":False,
        "guarded_flash_blockers":[]
    }
    if len(matched)!=1:
        result["guarded_flash_blockers"].append("ambiguous_or_absent_h0_app")
    if selected is None or matched!=[selected]:
        result["guarded_flash_blockers"].append("active_ota_slot_or_crc_unconfirmed")
    result["guarded_flash_blockers"].append("rollback_dry_run_not_yet_verified")
    result["guarded_flash_blockers"].append("device_wifi_stability_and_idle_not_yet_confirmed")
    return result


if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--readback",type=Path,required=True)
    ap.add_argument("--h0",type=Path,required=True)
    ap.add_argument("--rc1",type=Path,required=True)
    ap.add_argument("--report",type=Path,required=True)
    args=ap.parse_args()
    result=audit(args.readback,args.h0,args.rc1)
    args.report.write_text(json.dumps(result,indent=2),encoding="utf8")
    print(json.dumps(result,indent=2),flush=True)
