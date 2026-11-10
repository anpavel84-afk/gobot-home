"""Private Tailscale HTTPS transport launcher. No firewall or Tailscale Serve changes."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT / "services/brain"))
MANIFEST = ROOT / "run/browser.json"
IP = "100.90.228.125"
PORT = 18786
URL = "https://plan.tailffc57c.ts.net:18786"

def owned():
    import psutil
    if not MANIFEST.exists():
        return None
    data = json.loads(MANIFEST.read_text())
    try:
        process = psutil.Process(data["pid"])
        if abs(process.create_time() - data["created"]) < .1 and Path(process.cwd()).resolve() == ROOT:
            return process
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    return None

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["start", "serve", "stop", "status"])
    args = parser.parse_args()
    if args.command == "serve":
        import uvicorn, psutil
        from gobot.browser import create_browser_app
        MANIFEST.write_text(json.dumps({"pid": os.getpid(), "created": psutil.Process().create_time(), "url": URL}))
        try:
            uvicorn.run(create_browser_app(), host=IP, port=PORT, ssl_keyfile=str(ROOT/"run/tls/gobot.key"),
                        ssl_certfile=str(ROOT/"run/tls/gobot.crt"), proxy_headers=False,
                        access_log=False, log_level="warning", server_header=False)
        finally:
            MANIFEST.unlink(missing_ok=True)
    elif args.command == "start":
        if owned():
            print("GoBot HTTPS already running:", URL)
            return
        if not (ROOT/"run/tls/gobot.crt").exists():
            raise RuntimeError("Trusted TLS certificate is not ready")
        with socket.socket() as probe:
            probe.bind((IP, PORT))
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT/"services/brain")
        env["PYTHONUTF8"] = "1"
        with (ROOT/"run/browser.log").open("ab") as log:
            subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "serve"], cwd=ROOT,
                             env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                             creationflags=0x08000000 if os.name=="nt" else 0)
        for _ in range(50):
            if owned():
                time.sleep(.4)
                print("GoBot private HTTPS:", URL)
                return
            time.sleep(.1)
        raise RuntimeError("HTTPS gateway failed to start")
    elif args.command == "status":
        print(MANIFEST.read_text() if owned() else "HTTPS stopped")
    else:
        process=owned()
        if process:
            for child in reversed(process.children(recursive=True)):
                child.terminate()
            process.terminate()
            MANIFEST.unlink(missing_ok=True)
        print("HTTPS stopped; Brain and Bridge unchanged")

if __name__ == "__main__":
    main()
