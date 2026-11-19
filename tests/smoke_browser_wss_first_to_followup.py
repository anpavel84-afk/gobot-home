"""WSS 1st name -> MOCK response -> browser ACK -> local follow-up window.

Uses actual existing Vosk backend + HostCore, artificial PCM synthesized
locally on PLAN. No microphone, Spotpear, OpenAI API, or paid reservations.
"""
import asyncio,json,sys,time
from pathlib import Path
from websockets.asyncio.client import connect

TEST=Path(__file__).resolve().parent
sys.path.insert(0,str(TEST))
from smoke_browser_asr_does_not_stop import make_frames

async def main():
    input_frames=make_frames() + [bytes(1920)]*85
    received=set()
    errors=[]
    async with connect(
        "ws://127.0.0.1:18811/ws",
        origin="https://plan.tailffc57c.ts.net",
        max_size=131072,open_timeout=8,close_timeout=2,ping_interval=None
    ) as ws:
        await ws.send(json.dumps({"type":"hello","source":"BROWSER_MIC",
            "sink":"BROWSER_AUDIO","mode":"MOCK","sample_rate":16000}))
        async def consume():
            while True:
                data=await ws.recv()
                if isinstance(data,bytes):continue
                ev=json.loads(data)
                kind=ev.get("type")
                received.add(kind)
                if kind=="error":errors.append(str(ev.get("code")))
                if kind=="mock_speaker":
                    # Emulate the browser's actual SpeechSynthesis onend ACK.
                    await asyncio.sleep(.1)
                    await ws.send(json.dumps({"type":"playback_drained"}))
        sink=asyncio.create_task(consume())
        try:
            for frame in input_frames:
                await ws.send(frame)
                await asyncio.sleep(.060)
            await asyncio.sleep(1.3)
            print("FIRST_WAKE_WSS_STAGES", sorted(received))
            print("FIRST_WAKE_WSS_ERRORS", errors)
            if errors:raise RuntimeError(str(errors))
            assert "asr" in received and "wake" in received
            assert "cloud_final" in received
            assert "mock_speaker" in received
            assert "followup_wait" in received
            await ws.send(json.dumps({"type":"stop"}))
        finally:
            sink.cancel()
            await asyncio.gather(sink,return_exceptions=True)
    print("FIRST_WAKE_TO_FOLLOWUP_WSS_MOCK_PASS")

if __name__=="__main__":
    asyncio.run(main())
