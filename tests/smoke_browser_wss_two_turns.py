"""REAL browser WSS, ZERO API: initial Monika -> answer -> no-name reply.

Actual Vosk+HostCore+browser WSS; fake OpenAI WS; synthetic PCM only.
"""
import asyncio,json,sys
from pathlib import Path
from websockets.asyncio.client import connect
import numpy as np
T=Path(__file__).resolve().parent
sys.path.insert(0,str(T))
from smoke_browser_asr_does_not_stop import make_frames

async def main():
    stages=[]
    errors=[]
    async with connect("ws://127.0.0.1:18811/ws",
                       origin="https://plan.tailffc57c.ts.net",
                       max_size=131072,open_timeout=8,close_timeout=2,
                       ping_interval=None) as ws:
        await ws.send(json.dumps({
            "type":"hello","source":"BROWSER_MIC","sink":"BROWSER_AUDIO",
            "mode":"MOCK","sample_rate":16000}))
        async def receiver():
            while True:
                raw=await ws.recv()
                if isinstance(raw,bytes):continue
                msg=json.loads(raw)
                ev=msg.get("type")
                stages.append(ev)
                if ev=="error":errors.append(msg.get("code"))
                if ev=="mock_speaker":
                    await asyncio.sleep(.1)
                    await ws.send(json.dumps({"type":"playback_drained"}))
        reader=asyncio.create_task(receiver())
        async def send(frames):
            for frame in frames:
                await ws.send(frame)
                await asyncio.sleep(.06)
        try:
            await send(make_frames()+[bytes(1920)]*85)
            await asyncio.sleep(.7)
            assert stages.count("followup_wait")>=1, stages[-20:]
            # Speak continuously without any "Monika": local voice energy
            # detector must start a new turn, stream, commit on silence.
            sine=np.full(960,2100,dtype="<i2").tobytes()
            await send([bytes(1920)]*8+[sine]*20+[bytes(1920)]*22)
            await asyncio.sleep(.8)
            print("WSS_STAGES_NEW_DIALOGUE", {
                k:stages.count(k) for k in (
                    "wake", "followup_wait", "followup_speech_start",
                    "followup_audio_commit", "cloud_final",
                    "mock_speaker","playback_drained","error"
                )})
            print("WSS_ERRORS",errors)
            assert stages.count("wake")==1
            assert stages.count("followup_speech_start")>=1
            assert stages.count("followup_audio_commit")>=1
            assert stages.count("mock_speaker")>=2
            assert stages.count("followup_wait")>=2
            assert not errors
            await ws.send(json.dumps({"type":"stop"}))
        finally:
            reader.cancel();await asyncio.gather(reader,return_exceptions=True)
    print("BROWSER_WSS_TWO_TURNS_WITHOUT_REPEAT_NAME_PASS")

if __name__=="__main__":
    asyncio.run(main())
