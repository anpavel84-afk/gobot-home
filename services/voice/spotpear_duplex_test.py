"""Free physical-device media probe through the same local LiveKit relay."""
import asyncio
import numpy as np
from spotpear_livekit import LocalMediaRelay

async def local_probe(config,capture,turn_id,send,send_audio,encoder):
    relay=LocalMediaRelay(config["livekit_settings"],turn_id)
    counts={"microphone_frames":0,"speaker_frames":0,"nonzero_microphone_frames":0}
    try:
        await relay.connect()
        relay.task(relay.microphone(capture))
        async def play(pcm):
            counts["speaker_frames"]+=1
            for packet in encoder.feed(pcm,24000):await send_audio(packet)
        relay.task(relay.output(play))
        async def measure():
            while True:
                pcm=await relay.input_queue.get()
                counts["microphone_frames"]+=1
                raw=np.frombuffer(pcm,"<i2").astype(np.float64)
                if np.sqrt(np.mean(raw**2))>120:counts["nonzero_microphone_frames"]+=1
        relay.task(measure())
        await send({"type":"tts","state":"start"})
        begin=asyncio.get_running_loop().time()
        for i in range(400):
            if relay.error.done():relay.error.result()
            t=(np.arange(480)+i*480)/24000
            signal=(1800*(np.sin(2*np.pi*437*t)+.5*np.sin(2*np.pi*883*t))).astype("<i2")
            await relay.send_speaker(signal.tobytes())
            await asyncio.sleep(max(0,begin+(i+1)*.02-asyncio.get_running_loop().time()))
        await asyncio.sleep(1)
        for packet in encoder.finish():await send_audio(packet)
        await send({"type":"tts","state":"stop"})
        deadline=asyncio.get_running_loop().time()+3
        while capture.playing and asyncio.get_running_loop().time()<deadline:await asyncio.sleep(.05)
        return counts
    finally:await relay.close()
