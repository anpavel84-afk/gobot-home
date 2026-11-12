"""Actual two-participant loopback test, opt-in local server, no OpenAI."""
import asyncio
import json
import os
from pathlib import Path
import sys
import numpy as np
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"services/voice"))
pytest.importorskip("livekit")
from spotpear_livekit import LocalMediaRelay

@pytest.mark.skipif(not os.environ.get("GOBOT_LOCAL_LIVEKIT_TEST"),reason="Requires isolated loopback LiveKit")
def test_simultaneous_two_way_media():
    async def scenario():
        settings=json.loads(Path(os.environ["GOBOT_LOCAL_LIVEKIT_TEST"]).read_text())
        relay=LocalMediaRelay(settings,"fixture"+str(os.getpid()))
        try:
            await relay.connect()
            async def tx(source,rate,freq):
                from livekit import rtc
                for i in range(100):
                    t=(np.arange(rate//50)+i*(rate//50))/rate
                    raw=(4000*np.sin(t*freq*2*np.pi)).astype("<i2").tobytes()
                    await source.capture_frame(rtc.AudioFrame(raw,rate,1,rate//50))
                    await asyncio.sleep(.02)
            async def rx(queue):
                loud=0
                while loud<15:
                    pcm=await asyncio.wait_for(queue.get(),5)
                    if np.max(np.abs(np.frombuffer(pcm,"<i2").astype(np.int32)))>500:loud+=1
            await asyncio.wait_for(asyncio.gather(tx(relay.mic,16000,440),tx(relay.speaker,24000,880),
                  rx(relay.input_queue),rx(relay.output_queue)),10)
            assert relay.counts["input_frames"]>=15 and relay.counts["output_frames"]>=15
        finally:await relay.close()
    asyncio.run(scenario())
