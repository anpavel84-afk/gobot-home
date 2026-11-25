"""REAL Browser Lab handshake: actual Brain init, zero wake, zero paid calls."""
import asyncio
import json
from websockets.asyncio.client import connect


async def main():
    async with connect(
        "ws://127.0.0.1:18811/ws",
        origin="https://plan.tailffc57c.ts.net",
        open_timeout=8, close_timeout=3,
        ping_interval=None,
    ) as ws:
        await ws.send(json.dumps({
            "type": "hello", "source": "BROWSER_MIC",
            "sink": "BROWSER_AUDIO", "mode": "REAL",
            "paid_consent": True, "sample_rate": 16000,
        }))
        event = json.loads(await asyncio.wait_for(ws.recv(), timeout=18))
        print("REAL_BROWSER_WS_EVENT", event.get("type"),
              "MODE", event.get("mode"), "ERROR", event.get("code"))
        if event.get("type") != "ready" or event.get("mode") != "REAL":
            raise RuntimeError("real_browser_brain_initialization_failed")
        await ws.send(bytes(1920))
        got_signal = False
        for _ in range(6):
            response = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            if response.get("type") == "signal":
                got_signal = True
                break
            if response.get("type") == "error":
                raise RuntimeError("REAL_BROWSER_PCM_FAULT " +
                                   str(response.get("code")))
        print("REAL_BROWSER_PCM_ZERO_SILENCE", got_signal)
        await ws.send(json.dumps({"type": "stop"}))
        if not got_signal:
            raise RuntimeError("real_browser_audio_queue_not_processed")


if __name__ == "__main__":
    asyncio.run(main())
