"""In-process Brain API fixture and two real local WebRTC peers. No provider access."""
import asyncio
import io
import json
import os
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


def tone(amplitude=4000):
    sink = io.BytesIO()
    with wave.open(sink, "wb") as stream:
        stream.setparams((1, 2, 16000, 0, "NONE", ""))
        stream.writeframes((amplitude * np.sin(np.arange(6400)*.11)).astype("<i2").tobytes())
    return sink.getvalue()


@pytest.mark.parametrize("streaming",[False, True, "provider_end", "continuous", "continuous_slow_setup",
                                     "continuous_silent_idle","continuous_silent_fault","continuous_deferred"])
def test_live_roundtrip_and_close(streaming):
    continuous = isinstance(streaming,str) and streaming.startswith("continuous")
    silent = streaming in {"continuous_silent_idle","continuous_silent_fault"}
    deferred = streaming=='continuous_deferred'
    if continuous and not os.environ.get("GOBOT_LOCAL_LIVEKIT_TEST"):
        pytest.skip("Requires loopback LiveKit")
    async def scenario():
        remote = RTCPeerConnection(RTCConfiguration(iceServers=[]))
        input_received = asyncio.Event()
        output_received = asyncio.Event()
        controls, packets, closes = [], [], []
        ident = "spotpear-test-turn"
        consumed = []
        capture = StreamingSpeech() if streaming else tone()
        media_ready=asyncio.Event()
        if streaming and not deferred:
            with wave.open(io.BytesIO(tone(0 if silent else 4000))) as sample:
                capture.feed(sample.readframes(sample.getnframes()))
        if deferred:capture.deferred_start=True

        async def consume(track):
            while not input_received.is_set():
                frame = await track.recv()
                if silent or np.max(np.abs(frame.to_ndarray().astype(float))) > 100:
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
                        if not silent:
                            query={"type":"input_transcript","session_id":ident,"data":{"text":"Погода"}}
                            yield ("data: "+json.dumps(query)+"\n\n").encode()
                            await asyncio.wait_for(output_received.wait(),5)
                            if continuous:await asyncio.sleep(5)
                        else:await asyncio.sleep(.3)
                        closed={"type":"closed","session_id":ident,"data":{"final_usage_confirmed":True}}
                        if silent:closed['data']['reason']='idle_timeout' if streaming.endswith('idle') else 'sideband_closed'
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
            if streaming in {"continuous_slow_setup","continuous_deferred"}:
                await asyncio.sleep(5)
            await remote.setRemoteDescription(RTCSessionDescription(live_sdp(offer.sdp), "offer"))
            remote.addTrack(CapturedSpeech(tone(0 if silent else 4000)))
            await remote.setLocalDescription(await remote.createAnswer())
            return httpx.Response(200, json={"sdp":remote.localDescription.sdp, "session_id":ident,
                                    "model":"gpt-live-1", "configuration_confirmed":True})

        async def send(control):
            controls.append(control)
            if control['type']=='gobot_media_ready':media_ready.set()
            if control['type']=='gobot_input_end' and streaming=='provider_end':
                assert input_received.is_set() and not capture.finished
                capture.finish()
        async def send_audio(packet):
            packets.append(packet)
            if len(packets) >= 3:
                output_received.set()

        feeder = None
        if continuous:
            async def feed_microphone():
                if deferred:
                    await media_ready.wait()
                    with wave.open(io.BytesIO(tone())) as sample:
                        raw=sample.readframes(sample.getnframes())
                    for offset in range(0,len(raw),640):
                        capture.feed(raw[offset:offset+640]);await asyncio.sleep(.02)
                while True:
                    capture.feed(bytes(640))
                    await asyncio.sleep(.02)
            feeder = asyncio.create_task(feed_microphone())
            consumed.append(feeder)
        config = {"device_id":"spotpear-unit","conversation_id":"test-topic",
                  "brain_url":"http://127.0.0.1:18781","hardware_live_consent":True}
        if continuous:
            config["continuous_live"]=True
            config["livekit_settings"]=json.loads(Path(os.environ["GOBOT_LOCAL_LIVEKIT_TEST"]).read_text())
        try:
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                operation=live_turn(client,config,{},capture,ident,send,send_audio,OpusOutput())
                if streaming=='continuous_silent_fault':
                    with pytest.raises(ValueError,match='hardware_live_no_audio'):await asyncio.wait_for(operation,18)
                else:await asyncio.wait_for(operation, 18)
            if continuous:
                assert not capture.finished
                # A feeder failure used to be swallowed during cleanup, hiding a full input buffer.
                assert feeder is not None and not feeder.done(), feeder.exception() if feeder else None
                if deferred:
                    assert sum(c['type']=='gobot_media_ready' for c in controls)==1
                    assert capture.diagnostics()['peak_backlog_ms']<250
            tts=[control["state"] for control in controls if control["type"]=="tts"]
            if silent:
                assert not tts and not packets
                assert len(closes)==1
                return
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


@pytest.mark.skipif(not os.environ.get("GOBOT_LOCAL_LIVEKIT_TEST"),reason="Requires loopback LiveKit")
def test_slow_setup_is_cancelled_and_closed_once_without_retry():
    async def scenario():
        capture=StreamingSpeech()
        capture.created_at-=8
        requests=[]
        async def handler(request):
            body=json.loads(request.content)
            requests.append(body)
            if request.url.path.endswith("/command"):
                assert body["action"]=="end"
                return httpx.Response(200,json={"closed":True})
            await asyncio.Future()  # Lost setup reply; no automatic second create.
        config={"device_id":"fixture-timeout","conversation_id":"fixture-timeout",
                "brain_url":"http://unused.invalid","hardware_live_consent":True,
                "continuous_live":True,"livekit_settings":json.loads(
                    Path(os.environ["GOBOT_LOCAL_LIVEKIT_TEST"]).read_text())}
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(TimeoutError):
                await live_turn(client,config,{},capture,"fixture-timeout",None,None,OpusOutput())
        assert capture.readyState=="ended"
        assert len(requests)==2 and requests[-1]["action"]=="end"
    asyncio.run(scenario())
