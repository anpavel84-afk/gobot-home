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
def test_tracks_without_source_pcm_do_not_fill_application_queues():
    async def scenario():
        settings=json.loads(Path(os.environ["GOBOT_LOCAL_LIVEKIT_TEST"]).read_text())
        relay=LocalMediaRelay(settings,"quiet-fixture"+str(os.getpid()))
        try:
            await relay.connect()
            await asyncio.sleep(.8)  # Longer than the 500 ms application queue.
            assert relay.input_queue.empty() and relay.output_queue.empty()
            assert not relay.error.done() and relay.pre_source_frames>0
        finally:await relay.close()
    asyncio.run(scenario())


@pytest.mark.skipif(not os.environ.get("GOBOT_LOCAL_LIVEKIT_TEST"),reason="Requires isolated loopback LiveKit")
def test_speaker_concealment_does_not_keep_device_playback_alive():
    async def scenario():
        settings=json.loads(Path(os.environ["GOBOT_LOCAL_LIVEKIT_TEST"]).read_text())
        relay=LocalMediaRelay(settings,"tail-fixture"+str(os.getpid()))
        received=[]
        try:
            await relay.connect()
            async def consume():
                while True:received.append(await relay.output_queue.get())
            consumer=asyncio.create_task(consume())
            for i in range(40):
                t=(np.arange(480)+i*480)/24000
                await relay.send_speaker((4000*np.sin(t*(880 if i>=30 else 440)*2*np.pi)).astype('<i2').tobytes())
                await asyncio.sleep(.02)
            await asyncio.sleep(.5)
            at_end=len(received)
            assert at_end>=35
            # The distinct last 200 ms must survive the source-tail gate.
            final_marker=0
            for pcm in received:
                power=np.abs(np.fft.rfft(np.frombuffer(pcm,'<i2').astype(float)))
                frequency=np.fft.rfftfreq(len(pcm)//2,1/24000)
                if power[(frequency>800)&(frequency<960)].sum()>3*max(1,power[(frequency>380)&(frequency<500)].sum()):
                    final_marker+=1
            assert final_marker>=3
            await asyncio.sleep(.5)
            assert len(received)==at_end and not relay.error.done()
        finally:
            if 'consumer' in locals():
                consumer.cancel();await asyncio.gather(consumer,return_exceptions=True)
            await relay.close()
    asyncio.run(scenario())

@pytest.mark.skipif(not os.environ.get("GOBOT_LOCAL_LIVEKIT_TEST"),reason="Requires isolated loopback LiveKit")
def test_simultaneous_two_way_media():
    async def scenario():
        settings=json.loads(Path(os.environ["GOBOT_LOCAL_LIVEKIT_TEST"]).read_text())
        relay=LocalMediaRelay(settings,"fixture"+str(os.getpid()))
        try:
            await relay.connect()
            async def tx(send,rate,freq):
                for i in range(100):
                    t=(np.arange(rate//50)+i*(rate//50))/rate
                    raw=(4000*np.sin(t*freq*2*np.pi)).astype("<i2").tobytes()
                    await send(raw)
                    await asyncio.sleep(.02)
            async def rx(queue):
                loud=0
                while loud<90:
                    pcm=await asyncio.wait_for(queue.get(),5)
                    if np.max(np.abs(np.frombuffer(pcm,"<i2").astype(np.int32)))>500:loud+=1
            await asyncio.wait_for(asyncio.gather(tx(relay.send_microphone,16000,440),tx(relay.send_speaker,24000,880),
                  rx(relay.input_queue),rx(relay.output_queue)),10)
            assert relay.counts["input_frames"]>=90 and relay.counts["output_frames"]>=90
            assert not relay.error.done()
        finally:await relay.close()
    asyncio.run(scenario())
