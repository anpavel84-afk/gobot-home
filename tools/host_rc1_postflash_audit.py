"""Compare full pre-/post-install 16MiB readbacks without exposing private bytes."""
from __future__ import annotations
import argparse,hashlib,json
from pathlib import Path
from host_rc1_readback_audit import EXPECTED

APP_SHA256="5186b41a80d3f4155dd544fa1112975eca74fa4b979d62c275b6804626d13576"
PRE_SHA256="c7848a7f183fc27340e7872ff8e424fa135eb8a95862a43f5996dd3d4529269b"

def digest(x):return hashlib.sha256(x).hexdigest()

def audit(pre:Path,post:Path,app:Path):
    a=pre.read_bytes();b=post.read_bytes();new=app.read_bytes()
    if len(a)!=0x1000000 or len(b)!=0x1000000:raise ValueError("readback_length_incorrect")
    if digest(a)!=PRE_SHA256:raise ValueError("pre_readback_changed")
    if digest(new)!=APP_SHA256:raise ValueError("candidate_image_changed")
    regions={}
    # Every partition except the *active* ota_0 must remain byte-for-byte
    # identical. Also guard bootloader and partition map 0x0..0x1ffff.
    for name,(offset,length,kind) in EXPECTED.items():
        same=a[offset:offset+length]==b[offset:offset+length]
        regions[name]={"equal":same,"bytes":length}
    # Independent check: exclude NVS (0x9000..0xcfff) from boot/table guard.
    boot_same=(a[:0x9000]==b[:0x9000] and a[0xD000:0x20000]==b[0xD000:0x20000])
    active_addr=EXPECTED["ota_0"][0]
    installed=b[active_addr:active_addr+len(new)]
    app_same=installed==new
    if not app_same:raise ValueError("candidate_app_readback_mismatch")
    disallowed=[name for name in regions if name!="ota_0" and not regions[name]["equal"]]
    if not boot_same:disallowed.append("boot_and_partition_area")
    return {
        "read_only":True,"pre_sha256":digest(a),"post_sha256":digest(b),
        "active_slot":"ota_0","app_image_sha256":digest(new),
        "installed_app_matches":True,
        "boot_partition_nvs_ota1_assets_unchanged":not disallowed,
        "disallowed_changes":disallowed,
        "regions":regions,
        "whole_device_human_acceptance":False
    }

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--pre",type=Path,required=True)
    p.add_argument("--post",type=Path,required=True)
    p.add_argument("--app",type=Path,required=True)
    p.add_argument("--report",type=Path,required=True)
    x=p.parse_args();result=audit(x.pre,x.post,x.app)
    x.report.write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))
    if result["disallowed_changes"]:raise SystemExit(3)
