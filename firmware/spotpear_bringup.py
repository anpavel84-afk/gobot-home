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
    parser.add_argument("action", choices=["inspect", "install", "restore", "touch", "touch-audio", "touch-volume", "touch-auto", "previous", "wake-probe", "wake-rollback", "duplex", "duplex-rollback", "continuous", "continuous-rollback"])
    parser.add_argument("--hardware-data", type=Path, default=ROOT/"data/hardware",
                        help="Existing owner-private backup and enrollment directory")
    parser.add_argument("--resume-snapshot",type=Path,help="Resume this local guarded read, preserving completed four-MiB segments")
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
            time.sleep(.7)
            p = subprocess.run([sys.executable,"-m","esptool","--chip","esp32s3","-p",ports[0],"-b","921600",*map(str,args)],
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=420)
            if p.returncode and args[0]=="read-mac":
                time.sleep(1)
                p=subprocess.run([sys.executable,"-m","esptool","--chip","esp32s3","-p",ports[0],"-b","115200",*map(str,args)],
                                 stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=30)
            if p.returncode and args[0]=="read-flash":
                time.sleep(2)
                p=subprocess.run([sys.executable,"-m","esptool","--chip","esp32s3","-p",ports[0],"-b","460800",*map(str,args)],
                                 stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=420)
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
        # Bounded reads and reconnects avoid the Windows USB large-transfer stall.
        from esptool import cmds
        resume=opts.resume_snapshot.resolve() if opts.resume_snapshot else None
        start=0
        if resume:
            require(resume.is_relative_to(PRIVATE.resolve()) and resume.name=="before.bin" and resume.parent.name.startswith("operation-"),"Invalid private snapshot path")
            start=resume.stat().st_size
            require(0<start<0x1000000 and start%0x10000==0,"Snapshot is not a completed segment")
            snapshot.write_bytes(resume.read_bytes())
        with snapshot.open("ab" if start else "xb") as output:
            for segment in range(start,0x1000000,0x400000):
                device=None
                try:
                    for attempt in range(3):
                        try:
                            time.sleep(5)
                            device=cmds.detect_chip(port=ports[0],baud=460800).run_stub()
                            break
                        except Exception:
                            if attempt==2:raise
                    end=min(segment+0x400000,0x1000000)
                    known=original[segment:end]
                    observed=device.flash_md5sum(segment,len(known))
                    if observed.lower()==hashlib.md5(known).hexdigest():
                        output.write(known)
                        output.flush()
                        print("Snapshot segment verified against original by chip MD5",hex(segment),flush=True)
                        continue
                    for offset in range(segment,end,0x10000):
                        data=device.read_flash(offset,0x10000)
                        require(len(data)==0x10000,"Incomplete snapshot block")
                        output.write(data)
                    output.flush()
                    print("Snapshot progress",(segment+0x400000)//0x100000,"MiB",flush=True)
                finally:
                    if device is not None:
                        try:device.hard_reset()
                        finally:device._port.close()
                time.sleep(2)
        time.sleep(2)
        current = snapshot.read_bytes()
        require(len(current)==len(original), "Incomplete pre-operation backup")
        # Known ota_seq=1, valid state and CRC. Only NVS may differ on factory.
        require(current[:0x9000]==original[:0x9000] and current[0xd000:0x20000]==original[0xd000:0x20000], "Unexpected loader/table/OTA state")
        require(current[0x410000:0x800000] == original[0x410000:0x800000], "Inactive OTA slot changed")
        if opts.action=="install":
            require(current[0x20000:]==original[0x20000:], "Factory app/assets differ; review before install")
        require(original[0x8000:0x8c00]==(PRIVATE/"candidate/partition-table.bin").read_bytes(),"Partition geometry changed")
        if opts.action in ("touch","touch-audio","touch-volume","touch-auto","previous","wake-probe","wake-rollback","duplex","duplex-rollback","continuous","continuous-rollback"):
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
            if opts.action in ("wake-probe", "wake-rollback","duplex","duplex-rollback","continuous","continuous-rollback"):
                kw = json.loads((ROOT/"firmware/spotpear/microwake/installed.json").read_text())
                probe = PRIVATE/"touch/gobot-wake-probe.bin"
                require(probe.stat().st_size == kw["app_bytes"] <= 0x3f0000 and
                        digest(probe.read_bytes()) == kw["app_sha256"], "Wake binary mismatch")
                sources["wake-probe"] = (app, release["app_sha256"])
                sources["wake-rollback", "duplex", "duplex-rollback", "continuous", "continuous-rollback"] = (probe, kw["app_sha256"])
                target = probe if opts.action=="wake-probe" else app
            if opts.action in ("duplex", "duplex-rollback","continuous","continuous-rollback"):
                report = json.loads((ROOT/"firmware/spotpear/duplex/release.json").read_text())
                target_image = PRIVATE/"touch/gobot-duplex.bin"
                previous = PRIVATE/"touch/gobot-wake-probe.bin"
                require(digest(target_image.read_bytes()) == report["app_sha256"] and target_image.stat().st_size == report["app_bytes"] <= 0x3f0000,"Duplex candidate mismatch")
                require(digest(previous.read_bytes()) == report["previous_sha256"],"Wake rollback image mismatch")
                sources["duplex"] = (previous, report["previous_sha256"])
                sources["duplex-rollback", "continuous", "continuous-rollback"] = (target_image,report["app_sha256"])
                target = target_image if opts.action=="duplex" else previous
            if opts.action in ("continuous", "continuous-rollback"):
                report = json.loads((ROOT/"firmware/spotpear/duplex/continuous-release.json").read_text())
                new = PRIVATE/"touch/gobot-continuous.bin"
                previous = PRIVATE/"touch/gobot-duplex.bin"
                require(new.stat().st_size == report["app_bytes"] <= 0x3f0000 and digest(new.read_bytes()) == report["app_sha256"], "Continuous image mismatch")
                require(digest(previous.read_bytes()) == report["previous_sha256"], "Duplex rollback mismatch")
                sources["continuous"] = (previous,report["previous_sha256"])
                sources["continuous-rollback"] = (new,report["app_sha256"])
                target = new if opts.action=="continuous" else previous
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
