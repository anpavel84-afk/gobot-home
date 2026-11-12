"""Free full adapter probe: real loopback WebRTC/LiveKit, synthetic audio only."""
import asyncio
import json
import os
from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"services/voice"))
pytest.importorskip("aiortc")
from spotpear_duplex_test import local_probe
from spotpear_live import StreamingSpeech
from gobot_device_gateway import OpusOutput


@pytest.mark.skipif(not os.environ.get("GOBOT_LOCAL_LIVEKIT_TEST"),reason="Requires loopback LiveKit")
def test_delayed_setup_then_simultaneous_audio_no_provider():
    async def scenario():
        capture=StreamingSpeech()
        config={"mode":"duplex_test","continuous_live":True,"device_id":"fixture-board",
                "conversation_id":"fixture-topic","brain_url":"http://unused.invalid",
                "hardware_live_consent":True,"livekit_settings":json.loads(
                    Path(os.environ["GOBOT_LOCAL_LIVEKIT_TEST"]).read_text())}
        playing=False
        packets=0
        async def control(event):
            nonlocal playing
            if event["type"]=="tts":playing=event["state"]=="start"
        async def audio(packet):
            nonlocal packets
            assert playing and packet  # No pre-source comfort noise sent as a response.
            packets+=1
            await asyncio.sleep(.060)
        async def feed():
            samples=(1000*np.sin(np.arange(960)*.2)).astype("<i2").tobytes()
            while True:
                capture.feed(samples)
                await asyncio.sleep(.060)
        feeder=asyncio.create_task(feed())
        try:
            counts=await asyncio.wait_for(local_probe(config,capture,"fixture-hardware-probe",control,audio,OpusOutput()),20)
            assert not feeder.done(),feeder.exception()
            assert counts["provider_calls"]==0 and counts["fixture_closes"]==1
            assert counts["peak_input_backlog_ms"]>=5000
            assert counts["microphone_during_speaker"]>=100 and packets>100
        finally:
            feeder.cancel()
            await asyncio.gather(feeder,return_exceptions=True)
    asyncio.run(scenario())


def test_probe_cannot_be_used_in_live_mode():
    with pytest.raises(ValueError,match="free_continuous_probe_only"):
        asyncio.run(local_probe({"mode":"live_c"},None,"unused",None,None,None))
