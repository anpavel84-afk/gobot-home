"""Read-only non-content sector difference counts for two flash backups."""
from pathlib import Path
import argparse
p=argparse.ArgumentParser()
p.add_argument("--pre",type=Path,required=True)
p.add_argument("--post",type=Path,required=True)
a=p.parse_args()
pre=a.pre.read_bytes();post=a.post.read_bytes()
if len(pre)!=len(post) or len(pre)!=0x1000000:raise ValueError("flash_size")
print("NON_APP_CHANGED_SECTORS_START")
for addr in list(range(0,0x20000,0x1000))+list(range(0x410000,0x1000000,0x1000)):
    x=pre[addr:addr+4096];y=post[addr:addr+4096]
    if x!=y:
        changed=sum(v!=w for v,w in zip(x,y))
        print(f"sector={addr:#08x} changed_bytes={changed} region={('NVS' if 0x9000<=addr<0xD000 else 'OTHER')}")
print("NON_APP_CHANGED_SECTORS_END")
