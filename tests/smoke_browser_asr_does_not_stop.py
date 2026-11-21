"""Real WSS+real Vosk ASR regression with LOCAL synthetic speech only.
No physical microphone, no paid Cloud calls, no audio files.
"""
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path
import time

import av
import numpy as np
from websockets.asyncio.client import connect

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"services"/"voice"))
from host_local_tts import offline_russian_packets


def make_frames():
    voice=ROOT.parent/"GoBotHome"/"data"/"hardware"/"gobot-v1"/"irina.onnx"
    packets=offline_russian_packets(voice,text="Моника, сколько времени?")
    decoder=av.CodecContext.create("opus","r")
    resampler=av.AudioResampler(format="s16",layout="mono",rate=16000)
    pcm=bytearray(bytes(16000))
    for packet in packets:
        for frame in decoder.decode(av.Packet(packet)):
            for converted in resampler.resample(frame):
                pcm.extend(converted.to_ndarray().astype("<i2",copy=False).tobytes())
    pcm.extend(bytes(32000))
    # Enforce device's canonical PCM16 960-sample input exactly.
    usable=len(pcm)//1920*1920
    return [bytes(pcm[n:n+1920]) for n in range(0,usable,1920)]


async def main():
    source=make_frames()
    count=Counter()
    got_asr=False
    asynchronous_failure=None
    async with connect(
        "ws://127.0.0.1:18811/ws",
        origin="https://plan.tailffc57c.ts.net",
        open_timeout=8,close_timeout=3,ping_interval=None,
        max_size=131072,
    ) as ws:
        await ws.send(json.dumps({
            "type":"hello", "source":"BROWSER_MIC",
            "sink":"BROWSER_AUDIO","mode":"MOCK","sample_rate":16000
        }))
        hello=json.loads(await asyncio.wait_for(ws.recv(),timeout=10))
        assert hello.get("type")=="ready",hello
        marker=json.loads(await asyncio.wait_for(ws.recv(),timeout=3))
        assert marker.get("type")=="journal_status", marker

        async def receiver():
            nonlocal got_asr,asynchronous_failure
            try:
                while True:
                    msg=await ws.recv()
                    if isinstance(msg,bytes):continue
                    item=json.loads(msg)
                    event=item.get("type")
                    count[event]+=1
                    if event=="asr":got_asr=True
                    if event=="error":
                        asynchronous_failure=item.get("code")
            except Exception as e:
                asynchronous_failure=asynchronous_failure or type(e).__name__

        reader=asyncio.create_task(receiver())
        try:
            for packet in source:
                await ws.send(packet)
                await asyncio.sleep(.060)
                if asynchronous_failure:
                    break
            await asyncio.sleep(1.5)
            print("SYNTHETIC_PIPER_LOCAL_INPUT_FRAMES",len(source))
            print("RECEIVED_EVENTS",dict(count))
            print("WSS_ASR_EVENT_SEEN",got_asr)
            print("WSS_ERROR",asynchronous_failure)
            if asynchronous_failure:
                raise RuntimeError("WSS_SERVER_STOP_AFTER_REAL_ASR:"+asynchronous_failure)
            if not got_asr:
                raise RuntimeError("SYNTHETIC_ASR_NOT_EMITTED")
            # Sending another valid packet after Vosk emission must succeed.
            await ws.send(bytes(1920))
            await asyncio.sleep(.1)
            if asynchronous_failure:
                raise RuntimeError("WSS_DROPPED_AFTER_ASR")
            await ws.send(json.dumps({"type":"stop"}))
        finally:
            reader.cancel()
            await asyncio.gather(reader,return_exceptions=True)
    print("VOICE_LAB_SYNTHETIC_ASR_NO_STOP_PASS")


if __name__=="__main__":
    asyncio.run(main())
