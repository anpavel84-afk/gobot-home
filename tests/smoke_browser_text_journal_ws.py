"""Real local WebSocket smoke for full transcript journaling; mock/no API."""
import asyncio
import json
from pathlib import Path
import time
from websockets.asyncio.client import connect

ROOT = Path(__file__).resolve().parents[1]
LOGS = ROOT / "run" / "host-a" / "browser-lab" / "conversations"


async def main():
    before = set(LOGS.glob("session-*.jsonl")) if LOGS.exists() else set()
    async with connect("ws://127.0.0.1:18811/ws",
                       origin="https://plan.tailffc57c.ts.net",
                       open_timeout=7, close_timeout=2,
                       ping_interval=None) as ws:
        await ws.send(json.dumps({
            "type": "hello", "source": "BROWSER_MIC",
            "sink": "BROWSER_AUDIO", "mode": "MOCK",
            "sample_rate": 16000,
        }))
        ready = json.loads(await asyncio.wait_for(ws.recv(), timeout=12))
        if ready.get("type") != "ready":
            raise RuntimeError("LOCAL_LAB_HELLO_NOT_READY")
        marker = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        print("JOURNAL_MARKER", marker.get("type"),
              marker.get("filename", "NO_NAME"))
        if marker.get("type") != "journal_status":
            raise RuntimeError("JOURNAL_ACTIVE_MARKER_MISSING")
        for _ in range(18):
            await ws.send(bytes(1920))
            await asyncio.sleep(.06)
        await ws.send(json.dumps({"type": "stop"}))
    for _ in range(25):
        after = set(LOGS.glob("session-*.jsonl"))
        newfiles = after - before
        if newfiles:
            path = next(iter(newfiles))
            try:
                entries = [json.loads(s) for s in
                           path.read_text(encoding="utf-8").splitlines()]
            except OSError:
                await asyncio.sleep(.1)
                continue
            if any(e.get("stage") == "session_end" for e in entries):
                print("JOURNAL_FILE_CREATED", path.name)
                print("JOURNAL_STAGES",
                      list(dict.fromkeys(e["stage"] for e in entries)))
                assert entries[0]["stage"] == "session_start"
                assert entries[-1]["stage"] == "session_end"
                assert entries[-1]["complete"] is True
                assert entries[0]["raw_audio_saved"] is False
                assert any(e["stage"] == "ready" for e in entries)
                assert any(e["stage"] == "signal" for e in entries)
                print("FULL_LOCAL_JOURNAL_WEBSOCKET_PASS")
                return
        await asyncio.sleep(.1)
    raise RuntimeError("JOURNAL_NOT_FLUSHED_ON_BROWSER_WS_STOP")


if __name__ == "__main__":
    asyncio.run(main())
