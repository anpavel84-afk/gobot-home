"""In-process Brain API fixture and two real local WebRTC peers. No provider access."""
import asyncio
import io
import json
from pathlib import Path
import sys
import wave

import httpx
import numpy as np
import pytest

pytest.importorskip("aiortc")
from aiortc import RTCConfiguration, RTCPeerConnection, RTCSessionDescription
from gobot.live_contract import LiveOffer, live_sdp
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services/voice"))
from gobot_device_gateway import OpusInput, OpusOutput
from spotpear_live import CapturedSpeech, StreamingSpeech, live_turn


def tone():
    sink = io.BytesIO()
    with wave.open(sink, "wb") as stream:
        stream.setparams((1, 2, 16000, 0, "NONE", ""))
        stream.writeframes((4000 * np.sin(np.arange(6400)*.11)).astype("<i2").tobytes())
    return sink.getvalue()


@pytest.mark.parametrize("streaming",[False, True, "provider_end"])
def test_live_roundtrip_and_close(streaming):
    async def scenario():
        remote = RTCPeerConnection(RTCConfiguration(iceServers=[]))
        input_received = asyncio.Event()
        output_received = asyncio.Event()
        controls, packets, closes = [], [], []
        ident = "spotpear-test-turn"
        consumed = []
        capture = StreamingSpeech() if streaming else tone()
        if streaming:
            with wave.open(io.BytesIO(tone())) as sample:
                capture.feed(sample.readframes(sample.getnframes()))

        async def consume(track):
            while not input_received.is_set():
                frame = await track.recv()
                if np.max(np.abs(frame.to_ndarray().astype(float))) > 100:
                    input_received.set()
                    if streaming is True:
                        # The real remote WebRTC track already received speech before end-of-input.
                        capture.finish()

        @remote.on("track")
        def track_received(track):
            consumed.append(asyncio.create_task(consume(track)))

        async def handler(req):
            if req.method == "GET":
                assert req.url.params["client_id"] == "spotpear-unit"
                class Events(httpx.AsyncByteStream):
                    async def __aiter__(self):
                        await asyncio.wait_for(input_received.wait(),5)
                        query={"type":"input_transcript","session_id":ident,"data":{"text":"Погода"}}
                        yield ("data: "+json.dumps(query)+"\n\n").encode()
                        await asyncio.wait_for(output_received.wait(),5)
                        closed={"type":"closed","session_id":ident,"data":{"final_usage_confirmed":True}}
                        yield ("data: "+json.dumps(closed)+"\n\n").encode()
                return httpx.Response(200, stream=Events())
            body = json.loads(req.content)
            if req.url.path.endswith("/command"):
                if body['action'] == 'end':
                    closes.append(body)
                return httpx.Response(200, json={"closed":True})
            offer = LiveOffer.model_validate(body)
            assert offer.owner_test_binding is None and not offer.remember
            assert offer.device_id == offer.client_id == "spotpear-unit"
            await remote.setRemoteDescription(RTCSessionDescription(live_sdp(offer.sdp), "offer"))
            remote.addTrack(CapturedSpeech(tone()))
            await remote.setLocalDescription(await remote.createAnswer())
            return httpx.Response(200, json={"sdp":remote.localDescription.sdp, "session_id":ident,
                                    "model":"gpt-live-1", "configuration_confirmed":True})

        async def send(control):
            controls.append(control)
            if control['type']=='gobot_input_end' and streaming=='provider_end':
                assert input_received.is_set() and not capture.finished
                capture.finish()
        async def send_audio(packet):
            packets.append(packet)
            if len(packets) >= 3:
                output_received.set()

        config = {"device_id":"spotpear-unit","conversation_id":"test-topic",
                  "brain_url":"http://127.0.0.1:18781","hardware_live_consent":True}
        try:
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                await asyncio.wait_for(live_turn(client,config,{},capture,ident,send,send_audio,OpusOutput()), 9)
            tts=[control["state"] for control in controls if control["type"]=="tts"]
            assert tts==["start","stop"]
            if streaming=="provider_end":
                assert sum(control["type"]=="gobot_input_end" for control in controls)==1
            decoder = OpusInput()
            for packet in packets:
                decoder.feed(packet)
            assert len(decoder.wav()) > 3200
            assert len(closes) == 1 and closes[0]["action"] == "end"
        finally:
            await remote.close()
            for task in consumed:
                task.cancel()
            await asyncio.gather(*consumed, return_exceptions=True)
    asyncio.run(scenario())


def test_device_consent_precedes_media_or_api():
    with pytest.raises(PermissionError, match="hardware_live_permission_required"):
        asyncio.run(live_turn(None, {}, {}, b"", "unused", None, None, None))
