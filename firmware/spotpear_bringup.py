"""Spotpear experiment, pinned to one enrolled unit and one audited app/assets pair."""
import argparse, hashlib, json, os, re, subprocess, sys, time
from pathlib import Path
from serial.tools import list_ports

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / "data/hardware/gobot-v1"
FACTORY = ROOT / "data/hardware/factory/spotpear-factory-full-20261112.bin"
SECOND = Path(os.environ["LOCALAPPDATA"]) / "GoBotHome/FactoryBackups" / FACTORY.name
FACTORY_SHA = "1fe1e310d86425dbe2432133c8712aecb64262bb3649647a5104989de671f4e6"
IMAGES = {
    "gobot-app.bin": (0x20000, 0x3f0000, "5b7b14dc11722ddcf30feaf4afdcc266ed3ecb7eab00837fac3e35ee98fdaedf"),
    "gobot-assets.bin": (0x800000, 0x800000, "fc5373dae7272d6346e43f526a49807eb31d9b3c5836b16be87b94b663ff83e0"),
}

def require(ok, reason):
    if not ok:
        raise SystemExit(reason)

def digest(data):
    return hashlib.sha256(data).hexdigest()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["inspect", "install", "restore", "touch", "touch-audio", "touch-volume", "touch-auto", "previous", "wake-probe", "wake-rollback"])
    parser.add_argument("--hardware-data", type=Path, default=ROOT/"data/hardware",
                        help="Existing owner-private backup and enrollment directory")
    opts = parser.parse_args()
    global PRIVATE, FACTORY
    PRIVATE = opts.hardware_data.resolve()/"gobot-v1"
    FACTORY = opts.hardware_data.resolve()/"factory"/SECOND.name
    lock = PRIVATE / "bringup.lock"
    with lock.open("x") as f:
        f.write(str(os.getpid()))
    try:
        ports = [p.device for p in list_ports.comports() if (p.vid, p.pid) == (0x303a, 0x1001)]
        require(len(ports) == 1, "Expected exactly one Espressif USB JTAG port")
        def esp(*args):
            p = subprocess.run([sys.executable,"-m","esptool","--chip","esp32s3","-p",ports[0],"-b","921600",*map(str,args)],
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=420)
            require(p.returncode == 0, "esptool failed on " + str(args[0]))
            return p.stdout.decode(errors="replace")
        expected = json.loads((PRIVATE/"gateway.json").read_text())["device_mac"]
        require(expected.lower() in esp("read-mac").lower(), "Enrolled MAC mismatch")
        require("Detected flash size: 16MB" in esp("flash-id"), "Unexpected flash geometry")
        security = esp("get-security-info")
        require(all(s in security for s in ("Secure Boot: Disabled","Flash Encryption: Disabled")), "Unexpected security state")
        original = FACTORY.read_bytes()
        require(len(original)==0x1000000 and all(digest(p.read_bytes())==FACTORY_SHA for p in (FACTORY,SECOND,PRIVATE/"preflash-current.bin")), "Backup mismatch")
        directory = PRIVATE / ("operation-" + str(time.time_ns()))
        directory.mkdir()
        snapshot = directory / "before.bin"
        print("Reading fresh full flash", ports[0], flush=True)
        esp("read-flash",0,"0x1000000",snapshot)
        current = snapshot.read_bytes()
        require(len(current)==len(original), "Incomplete pre-operation backup")
        # Known ota_seq=1, valid state and CRC. Only NVS may differ on factory.
        require(current[:0x9000]==original[:0x9000] and current[0xd000:0x20000]==original[0xd000:0x20000], "Unexpected loader/table/OTA state")
        require(current[0x410000:0x800000] == original[0x410000:0x800000], "Inactive OTA slot changed")
        if opts.action=="install":
            require(current[0x20000:]==original[0x20000:], "Factory app/assets differ; review before install")
        require(original[0x8000:0x8c00]==(PRIVATE/"candidate/partition-table.bin").read_bytes(),"Partition geometry changed")
        if opts.action in ("touch","touch-audio","touch-volume","touch-auto","previous","wake-probe","wake-rollback"):
            release = json.loads((ROOT/"firmware/spotpear/touch_release.json").read_text())
            app = PRIVATE / "touch/gobot-touch-auto.bin"
            old = PRIVATE / "candidate/gobot-app.bin"
            assets = PRIVATE / "candidate/gobot-assets.bin"
            require(digest(app.read_bytes()) == release["app_sha256"] and app.stat().st_size==release["app_bytes"] and app.stat().st_size<=0x3f0000, "Unexpected touch candidate")
            require(digest(old.read_bytes()) == IMAGES["gobot-app.bin"][2], "Previous app mismatch")
            require(digest(assets.read_bytes()) == IMAGES["gobot-assets.bin"][2] == release["assets_sha256"], "Shared assets mismatch")
            require(current[0x800000:0x800000+assets.stat().st_size]==assets.read_bytes(), "Installed assets changed")
            sources = {
                "touch": (old, IMAGES["gobot-app.bin"][2]),
                "touch-audio": (PRIVATE/"touch/gobot-touch.bin", release["previous_ui_sha256"]),
                "touch-volume": (PRIVATE/"touch/gobot-touch-audio.bin", release["previous_audio_sha256"]),
                "touch-auto": (PRIVATE/"touch/gobot-touch-volume.bin", release["previous_volume_sha256"]),
                "previous": (app, release["app_sha256"]),
            }
            target = old if opts.action=="previous" else app
            if opts.action in ("wake-probe", "wake-rollback"):
                kw = json.loads((ROOT/"firmware/spotpear/microwake/installed.json").read_text())
                probe = PRIVATE/"touch/gobot-wake-probe.bin"
                require(probe.stat().st_size == kw["app_bytes"] <= 0x3f0000 and
                        digest(probe.read_bytes()) == kw["app_sha256"], "Wake binary mismatch")
                sources["wake-probe"] = (app, release["app_sha256"])
                sources["wake-rollback"] = (probe, kw["app_sha256"])
                target = probe if opts.action=="wake-probe" else app
            source, expected_sha = sources[opts.action]
            require(digest(source.read_bytes())==expected_sha, "Source image mismatch")
            require(current[0x20000:0x20000+source.stat().st_size]==source.read_bytes(),"Unexpected running image")
            print("Verified preflash snapshot; writing only ota_0",hex(0x20000),target.stat().st_size,digest(target.read_bytes()),flush=True)
            esp("write-flash","0x20000",target)
            esp("verify-flash","0x20000",target)
            print("Installed app verified on device", flush=True)
            return
        parts = []
        for name,(offset,limit,sha) in IMAGES.items():
            if opts.action=="restore":
                path=directory/("restore-"+name)
                path.write_bytes(original[offset:offset+limit])
            else:
                path=PRIVATE/"candidate"/name
                require(digest(path.read_bytes())==sha and path.stat().st_size<=limit,"Candidate changed")
            print(opts.action,hex(offset),path.stat().st_size,digest(path.read_bytes()),flush=True)
            if opts.action=="inspect":
                present = current[offset:offset+path.stat().st_size]
                print("candidate_matches_device", name, present == path.read_bytes(), flush=True)
            parts.extend((hex(offset),path))
        if opts.action!="inspect":
            esp("write-flash",*parts)
            esp("verify-flash",*parts)
            print("Written and verified on device",flush=True)
    finally:
        lock.unlink()

if __name__=="__main__":
    main()
