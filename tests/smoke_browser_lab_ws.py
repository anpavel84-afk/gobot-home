"""Zero-cost actual PLAN loopback WebSocket + PCM16 smoke. No PC mic."""
import asyncio
import json
from websockets.asyncio.client import connect


async def main():
    uri = "ws://127.0.0.1:18811/ws"
    async with connect(
        uri, origin="http://127.0.0.1:18811", open_timeout=7,
        close_timeout=2, ping_interval=None,
    ) as ws:
        await ws.send(json.dumps({
            "type": "hello", "source": "BROWSER_MIC",
            "sink": "BROWSER_AUDIO", "mode": "MOCK", "sample_rate": 16000,
        }))
        result = json.loads(await asyncio.wait_for(ws.recv(), timeout=12))
        print("BROWSER_LAB_WEBSOCKET_HELLO", result.get("type"))
        if result.get("type") != "ready":
            raise RuntimeError("browser_audio_source_not_ready")
        seen_signal = False
        for _ in range(15):
            await ws.send(bytes(1920))
            await asyncio.sleep(.062)
            try:
                while True:
                    message = json.loads(
                        await asyncio.wait_for(ws.recv(), timeout=.009))
                    if message.get("type") == "signal":
                        seen_signal = True
                    if message.get("type") == "error":
                        raise RuntimeError("browser_lab_error:" +
                                           str(message.get("code")))
            except asyncio.TimeoutError:
                pass
        print("BROWSER_LAB_REAL_WS_PCM_SIGNAL", seen_signal)
        await ws.send(json.dumps({"type": "stop"}))
        if not seen_signal:
            raise RuntimeError("browser_microphone_frame_not_processed")


if __name__ == "__main__":
    asyncio.run(main())
