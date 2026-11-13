"""Spotpear experiment, pinned to one enrolled unit and one audited app/assets pair."""
import argparse, hashlib, json, os, re, struct, subprocess, sys, time
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


def nvs_records(data):
    """Fingerprint logical records, not NVS allocation/erase bookkeeping."""
    records, namespaces = {}, {}
    pages = sorted((struct.unpack_from('<I',data,a+4)[0],data[a:a+4096])
                   for a in range(0x9000,0xd000,4096)
                   if struct.unpack_from('<I',data,a)[0] in (0xfffffffe,0xfffffffc))
    require(bool(pages),"No readable NVS pages")
    for _,page in pages:
        i=0
        while i<126:
            state=(page[32+i//4]>>((i%4)*2))&3
            if state!=2:i+=1;continue
            e=page[64+i*32:96+i*32]
            ns,kind,span,chunk=e[:4]
            key=e[8:24].split(b'\0')[0]
            require(1<=span<=126-i and bool(re.fullmatch(rb'[A-Za-z_][A-Za-z0-9_.-]{0,14}',key)),"Unexpected NVS record")
            value=e[24:]+page[64+(i+1)*32:64+(i+span)*32]
            records[(ns,key,kind,chunk)]=digest(value)
            if ns==0 and kind==1:namespaces[key]=e[24]
            i+=span
    return records,namespaces


def verify_nvs_config(before,after):
    a,ns=nvs_records(before);b,new_ns=nvs_records(after)
    require(ns==new_ns and b'phy' in ns,"NVS namespaces changed")
    changed=[k for k in a.keys()|b.keys() if a.get(k)!=b.get(k)]
    # ESP-IDF may refresh RF calibration during the deliberate boot resets.
    # No exemption for enrollment, network settings, volume or any other key.
    require(all(k[0]==ns[b'phy'] and k[1]==b'cal_data' for k in changed),"NVS configuration changed")
    return bool(changed)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["inspect", "install", "restore", "touch", "touch-audio", "touch-volume", "touch-auto", "previous", "wake-probe", "wake-rollback", "duplex", "duplex-rollback", "continuous", "continuous-rollback", "session-ack", "session-ack-rollback", "media-ready", "media-ready-rollback", "voice-status", "voice-status-rollback"])
    parser.add_argument("--hardware-data", type=Path, default=ROOT/"data/hardware",
                        help="Existing owner-private backup and enrollment directory")
    parser.add_argument("--resume-snapshot",type=Path,help="Resume this local guarded read, preserving completed four-MiB segments")
    parser.add_argument("--known-snapshot",type=Path,help="Existing full private snapshot, reused only where chip MD5 matches")
    opts = parser.parse_args()
    global PRIVATE, FACTORY
    PRIVATE = opts.hardware_data.resolve()/"gobot-v1"
    FACTORY = opts.hardware_data.resolve()/"factory"/SECOND.name
    manifests={"duplex":"release.json","duplex-rollback":"release.json",
               "continuous":"continuous-release.json","continuous-rollback":"continuous-release.json",
               "session-ack":"ack-release.json","session-ack-rollback":"ack-release.json",
               "media-ready":"media-ready-release.json","media-ready-rollback":"media-ready-release.json"}
    if opts.action in manifests:
        require((ROOT/"firmware/spotpear/duplex"/manifests[opts.action]).is_file(),"Release manifest missing")
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
        known_image=original
        if opts.known_snapshot:
            path=opts.known_snapshot.resolve()
            require(path.is_relative_to(PRIVATE.resolve()) and path.name=="before.bin" and path.stat().st_size==0x1000000,"Invalid known snapshot")
            known_image=path.read_bytes()
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
                    known=known_image[segment:end]
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
        if opts.action in ("voice-status", "voice-status-rollback"):
            report=json.loads((ROOT/"firmware/spotpear/voice_status/BUILD_MANIFEST.json").read_text())
            previous_report=json.loads((ROOT/"firmware/spotpear/duplex/media-ready-release.json").read_text())
            new=PRIVATE/"touch/gobot-voice-status.bin"
            previous=PRIVATE/"touch/gobot-media-ready.bin"
            require(report["version"]=="0.4.4-dev-voice-status-1" and report["sha256"]=="ed6aff97a300169cc53852022a5ff6b08fb448d82bec4934182513e007b54866", "Unapproved UI candidate")
            require(new.stat().st_size==report["bytes"]<=0x3f0000 and digest(new.read_bytes())==report["sha256"],"UI image mismatch")
            require(previous.stat().st_size==previous_report["app_bytes"] and digest(previous.read_bytes())==previous_report["app_sha256"],"Media-ready rollback mismatch")
            assets=PRIVATE/"candidate/gobot-assets.bin"
            require(digest(assets.read_bytes())==IMAGES["gobot-assets.bin"][2] and current[0x800000:0x800000+assets.stat().st_size]==assets.read_bytes(),"Installed assets changed")
            source,target=(previous,new) if opts.action=="voice-status" else (new,previous)
            require(current[0x20000:0x20000+source.stat().st_size]==source.read_bytes(),"Unexpected running image")
            print("Verified preflash snapshot; writing only ota_0",hex(0x20000),target.stat().st_size,digest(target.read_bytes()),flush=True)
            esp("write-flash","0x20000",target)
            esp("verify-flash","0x20000",target)
            # Independently verify all non-application regions including NVS,
            # enrollment, boot/OTA metadata, inactive slot and shared assets.
            device=None
            try:
                time.sleep(5)
                device=cmds.detect_chip(port=ports[0],baud=460800).run_stub()
                after_prefix=device.read_flash(0,0x20000)
                require(after_prefix[:0x9000]==current[:0x9000] and after_prefix[0xd000:]==current[0xd000:0x20000],"Boot/OTA metadata changed")
                recalibrated=verify_nvs_config(current,after_prefix)
                for offset,size in ((0x410000,0x3f0000),(0x800000,0x800000)):
                    require(device.flash_md5sum(offset,size).lower()==hashlib.md5(current[offset:offset+size]).hexdigest(),"Non-app region changed")
            finally:
                if device is not None:
                    try:device.hard_reset()
                    finally:device._port.close()
            print("Installed UI app verified; NVS configuration/boot/inactive slot/assets unchanged; RF recalibration="+str(recalibrated),flush=True)
            return
        if opts.action in ("touch","touch-audio","touch-volume","touch-auto","previous","wake-probe","wake-rollback","duplex","duplex-rollback","continuous","continuous-rollback","session-ack","session-ack-rollback","media-ready","media-ready-rollback"):
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
            if opts.action in ("wake-probe", "wake-rollback","duplex","duplex-rollback","continuous","continuous-rollback","session-ack","session-ack-rollback","media-ready","media-ready-rollback"):
                kw = json.loads((ROOT/"firmware/spotpear/microwake/installed.json").read_text())
                probe = PRIVATE/"touch/gobot-wake-probe.bin"
                require(probe.stat().st_size == kw["app_bytes"] <= 0x3f0000 and
                        digest(probe.read_bytes()) == kw["app_sha256"], "Wake binary mismatch")
                sources["wake-probe"] = (app, release["app_sha256"])
                for action in ("wake-rollback", "duplex", "duplex-rollback", "continuous", "continuous-rollback", "session-ack", "session-ack-rollback", "media-ready", "media-ready-rollback"):
                    sources[action] = (probe, kw["app_sha256"])
                target = probe if opts.action=="wake-probe" else app
            if opts.action in ("duplex", "duplex-rollback","continuous","continuous-rollback","session-ack","session-ack-rollback","media-ready","media-ready-rollback"):
                report = json.loads((ROOT/"firmware/spotpear/duplex/release.json").read_text())
                target_image = PRIVATE/"touch/gobot-duplex.bin"
                previous = PRIVATE/"touch/gobot-wake-probe.bin"
                require(digest(target_image.read_bytes()) == report["app_sha256"] and target_image.stat().st_size == report["app_bytes"] <= 0x3f0000,"Duplex candidate mismatch")
                require(digest(previous.read_bytes()) == report["previous_sha256"],"Wake rollback image mismatch")
                sources["duplex"] = (previous, report["previous_sha256"])
                for action in ("duplex-rollback", "continuous", "continuous-rollback", "session-ack", "session-ack-rollback", "media-ready", "media-ready-rollback"):
                    sources[action] = (target_image,report["app_sha256"])
                target = target_image if opts.action=="duplex" else previous
            if opts.action in ("continuous", "continuous-rollback","session-ack","session-ack-rollback","media-ready","media-ready-rollback"):
                report = json.loads((ROOT/"firmware/spotpear/duplex/continuous-release.json").read_text())
                new = PRIVATE/"touch/gobot-continuous.bin"
                previous = PRIVATE/"touch/gobot-duplex.bin"
                require(new.stat().st_size == report["app_bytes"] <= 0x3f0000 and digest(new.read_bytes()) == report["app_sha256"], "Continuous image mismatch")
                require(digest(previous.read_bytes()) == report["previous_sha256"], "Duplex rollback mismatch")
                sources["continuous"] = (previous,report["previous_sha256"])
                for action in ("continuous-rollback", "session-ack", "session-ack-rollback", "media-ready", "media-ready-rollback"):
                    sources[action] = (new,report["app_sha256"])
                target = new if opts.action=="continuous" else previous
            if opts.action in ("session-ack", "session-ack-rollback", "media-ready", "media-ready-rollback"):
                report=json.loads((ROOT/"firmware/spotpear/duplex/ack-release.json").read_text())
                new=PRIVATE/"touch/gobot-session-ack.bin"
                previous=PRIVATE/"touch/gobot-continuous.bin"
                require(new.stat().st_size==report["app_bytes"] <=0x3f0000 and digest(new.read_bytes())==report["app_sha256"],"ACK image mismatch")
                require(digest(previous.read_bytes())==report["previous_sha256"],"Continuous rollback mismatch")
                sources["session-ack"]=(previous,report["previous_sha256"])
                sources["session-ack-rollback"]=(new,report["app_sha256"])
                target=new if opts.action=="session-ack" else previous
            if opts.action in ("media-ready", "media-ready-rollback"):
                report=json.loads((ROOT/"firmware/spotpear/duplex/media-ready-release.json").read_text())
                new=PRIVATE/"touch/gobot-media-ready.bin"
                previous=PRIVATE/"touch/gobot-session-ack.bin"
                require(new.stat().st_size==report["app_bytes"] <=0x3f0000 and digest(new.read_bytes())==report["app_sha256"],"Media-ready image mismatch")
                require(digest(previous.read_bytes())==report["previous_sha256"],"ACK rollback mismatch")
                sources["media-ready"]=(previous,report["previous_sha256"])
                sources["media-ready-rollback"]=(new,report["app_sha256"])
                target=new if opts.action=="media-ready" else previous
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
