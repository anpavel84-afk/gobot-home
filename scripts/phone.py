"""Start/stop only the temporary Wi-Fi mock demonstration gateway."""
import argparse
import asyncio
import ipaddress
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
MANIFEST = ROOT / "run/phone.json"


def owned():
    import psutil
    if not MANIFEST.exists():
        return None
    saved = json.loads(MANIFEST.read_text(encoding="utf-8"))
    try:
        process = psutil.Process(saved["pid"])
        if abs(process.create_time() - saved["created"]) < .1 and Path(process.cwd()).resolve() == ROOT:
            return process
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    return None


def start(args):
    import psutil
    import httpx
    if owned():
        print("Phone demo already running:", json.loads(MANIFEST.read_text())["url"])
        return
    host = ipaddress.ip_address(args.host)
    assigned = {item.address for entries in psutil.net_if_addrs().values() for item in entries
                if item.family == socket.AF_INET}
    if str(host) not in assigned or not host.is_private or host.is_loopback:
        raise ValueError("Host must be this computer's specific Wi-Fi IPv4")
    with socket.socket() as probe:
        probe.bind((str(host), args.port))
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "services/brain")
    env["PYTHONUTF8"] = "1"
    command = [sys.executable, str(Path(__file__).resolve()), "serve", "--host", str(host),
               "--prefix", str(args.prefix), "--port", str(args.port), "--minutes", str(args.minutes)]
    with (ROOT / "run/phone.log").open("ab") as log:
        subprocess.Popen(command, cwd=ROOT, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                         **({"creationflags": 0x08000000} if os.name == "nt" else {"start_new_session": True}))
    url = "http://" + str(host) + ":" + str(args.port)
    with httpx.Client(trust_env=False, timeout=.5) as client:
        for _ in range(50):
            try:
                if client.get(url + "/api/status").status_code == 200:
                    print("Phone mock demo ready:", url, "| lifetime:", str(args.minutes)+" minutes" if args.minutes else "until owner stops it")
                    return
            except httpx.HTTPError:
                pass
            time.sleep(.2)
    raise RuntimeError("Phone demo startup failed; see run/phone.log")


async def serve(args):
    import psutil
    import uvicorn
    from gobot.phone import create_phone_app
    from gobot.config import load
    expires = time.time() + args.minutes * 60 if args.minutes else None
    app = create_phone_app(load().api_token, args.host, str(ipaddress.ip_network(
        args.host + "/" + str(args.prefix), strict=False)), args.port, expires)
    server = uvicorn.Server(uvicorn.Config(app, host=args.host, port=args.port, access_log=False,
                                         log_level="warning", server_header=False, proxy_headers=False))
    MANIFEST.write_text(json.dumps({"pid": os.getpid(), "created": psutil.Process().create_time(),
                                   "url": "http://" + args.host + ":" + str(args.port),
                                   "expires_at": expires}, indent=2), encoding="utf-8")
    async def expiry():
        await asyncio.sleep(args.minutes * 60)
        server.should_exit = True
    timer = asyncio.create_task(expiry()) if args.minutes else None
    try:
        await server.serve()
    finally:
        if timer:
            timer.cancel()
            await asyncio.gather(timer, return_exceptions=True)
        if MANIFEST.exists() and json.loads(MANIFEST.read_text())["pid"] == os.getpid():
            MANIFEST.unlink()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["start", "serve", "stop", "status"])
    parser.add_argument("--host", default="192.168.3.15")
    parser.add_argument("--prefix", type=int, default=24)
    parser.add_argument("--port", type=int, default=18785)
    parser.add_argument("--minutes", type=int, default=0, help="0: until explicitly stopped")
    args = parser.parse_args()
    if not 0 <= args.minutes <= 120 or not 16 <= args.prefix <= 30:
        parser.error("Lifetime 0 (unlimited) or 1..120 minutes; prefix 16..30")
    if args.command == "start":
        start(args)
    elif args.command == "serve":
        asyncio.run(serve(args))
    elif args.command == "status":
        print(MANIFEST.read_text() if owned() else "Phone demo stopped")
    else:
        process = owned()
        if process:
            for child in reversed(process.children(recursive=True)):
                child.terminate()
            process.terminate()
            MANIFEST.unlink(missing_ok=True)
        print("Phone demo stopped; other GoBot services unchanged")


if __name__ == "__main__":
    main()
