"""Download the official standalone binary, verify its published SHA-512, no global setup."""
import hashlib,json,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
MANIFEST='https://antigravity-cli-auto-updater-974169037036.us-central1.run.app/manifests/windows_amd64.json'
def main():
    item=json.load(urllib.request.urlopen(MANIFEST,timeout=30))
    if not item['url'].startswith('https://storage.googleapis.com/antigravity-public/antigravity-cli/') or len(item['sha512'])!=128:raise RuntimeError('unrecognized official manifest')
    directory=ROOT/'run/tools/antigravity'/item['version'];directory.mkdir(parents=True,exist_ok=True)
    binary=directory/'agy.exe'
    if not binary.exists():
        temporary=directory/'agy.exe.part'
        with urllib.request.urlopen(item['url'],timeout=60) as source,temporary.open('wb') as out:
            while chunk:=source.read(1048576):out.write(chunk)
        if hashlib.sha512(temporary.read_bytes()).hexdigest()!=item['sha512']:raise RuntimeError('binary checksum mismatch')
        temporary.replace(binary)
    if hashlib.sha512(binary.read_bytes()).hexdigest()!=item['sha512']:raise RuntimeError('existing binary checksum mismatch')
    report={**item,'source_manifest':MANIFEST,'sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),
            'relative_binary':str(binary.relative_to(ROOT)),'global_setup_executed':False,'path_modified':False}
    (ROOT/'docs/antigravity.lock.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({'installed':True,'version':item['version'],'binary':str(binary),'sha512_verified':True,'global_changes':False}))
if __name__=='__main__':main()
