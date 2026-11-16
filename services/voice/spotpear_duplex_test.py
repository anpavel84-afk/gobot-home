"""Free hardware probe through LiveKit AND the production WebRTC adapter.

The remote speech peer below is synthetic, not Brain or a provider. All HTTP is
intercepted in process. No text, microphone recording or external API is used.
"""
import asyncio
import io
import json
import wave
import numpy as np
import httpx
from aiortc import RTCConfiguration, RTCPeerConnection, RTCSessionDescription
from aiortc.mediastreams import MediaStreamError
from spotpear_live import CapturedSpeech, live_turn

async def local_probe(config,capture,turn_id,send,send_audio,encoder):
    if config.get("mode")!="duplex_test" or config.get("continuous_live") is not True:
        raise ValueError("free_continuous_probe_only")
    peer=RTCPeerConnection(RTCConfiguration(iceServers=[]))
    counts={"microphone_frames":0,"speaker_frames":0,"nonzero_microphone_frames":0,
            "microphone_during_speaker":0,"fixture_closes":0}
    tasks=[]
    input_ready=asyncio.Event()
    output_ready=asyncio.Event()
    tone_start=None
    tone_end=None
    t=np.arange(16000*8)/16000
    raw=(1800*(np.sin(2*np.pi*437*t)+.5*np.sin(2*np.pi*883*t))).astype("<i2").tobytes()
    sink=io.BytesIO()
    with wave.open(sink,"wb") as wav:
        wav.setparams((1,2,16000,0,"NONE",""));wav.writeframes(raw)
    class Sound(CapturedSpeech):
        async def recv(self):
            nonlocal tone_start,tone_end
            await input_ready.wait()
            frame=await super().recv()
            if self.position<=16000*8:
                counts["speaker_frames"]+=1
                if tone_start is None:tone_start=asyncio.get_running_loop().time()
                tone_end=asyncio.get_running_loop().time()
            return frame
    @peer.on("track")
    def track_received(track):
        async def consume():
            while True:
                try:frame=await track.recv()
                except MediaStreamError:
                    if capture.readyState=="ended":return
                    raise
                counts["microphone_frames"]+=1
                pcm=frame.to_ndarray().astype(np.float64)
                if np.sqrt(np.mean(pcm**2))>120:counts["nonzero_microphone_frames"]+=1
                if tone_start is not None and asyncio.get_running_loop().time()-tone_start<8:
                    counts["microphone_during_speaker"]+=1
                if capture.input_seen:input_ready.set()
        tasks.append(asyncio.create_task(consume()))
    async def handler(request):
        if request.method=="GET":
            class Events(httpx.AsyncByteStream):
                async def __aiter__(self):
                    await asyncio.wait_for(output_ready.wait(),8)
                    await asyncio.sleep(8.3)
                    yield ("data: "+json.dumps({"type":"closed","session_id":turn_id,
                           "data":{"final_usage_confirmed":True}})+"\n\n").encode()
            return httpx.Response(200,stream=Events())
        data=json.loads(request.content)
        if request.url.path.endswith("/command"):
            if data.get("action")=="end":counts["fixture_closes"]+=1
            return httpx.Response(200,json={"closed":True})
        if data.get("session_id")!=turn_id or data.get("remember") is not False:
            raise ValueError("unexpected_free_probe_offer")
        # Reproduce the setup delay which used to fill the four-second buffer.
        await asyncio.sleep(5)
        await peer.setRemoteDescription(RTCSessionDescription(data["sdp"],"offer"))
        peer.addTrack(Sound(sink.getvalue()))
        await peer.setLocalDescription(await peer.createAnswer())
        return httpx.Response(200,json={"session_id":turn_id,"sdp":peer.localDescription.sdp,
                                      "model":"gpt-live-1","configuration_confirmed":True})
    async def delivered(packet):
        output_ready.set()
        await send_audio(packet)
    try:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler),trust_env=False) as client:
            await live_turn(client,config,{},capture,turn_id,send,delivered,encoder)
        deadline=asyncio.get_running_loop().time()+3
        while capture.playing and asyncio.get_running_loop().time()<deadline:await asyncio.sleep(.05)
        for task in tasks:
            if task.done():task.result()
        counts.update({"peak_input_backlog_ms":capture.diagnostics()["peak_backlog_ms"],
                       "input_backlog_ms":capture.diagnostics()["backlog_ms"],
                       "setup_delay_ms":5000,"provider_calls":0})
        if (counts["microphone_during_speaker"]<100 or counts["fixture_closes"]!=1
                or not tone_end or tone_end-tone_start<7.8):
            raise ValueError("free_duplex_media_incomplete")
        return counts
    finally:
        for task in tasks:task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        await peer.close()
