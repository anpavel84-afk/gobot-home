"""One post-wake Spotpear utterance over the existing Brain C WebRTC/SSE entry points."""
import asyncio
from contextlib import suppress
from fractions import Fraction
import io
import json
import uuid
import wave

import av
import numpy as np
from aiortc import AudioStreamTrack, RTCConfiguration, RTCPeerConnection, RTCSessionDescription


class CapturedSpeech(AudioStreamTrack):
    """Clock one authorized utterance into WebRTC; pad subsequent frames with silence."""
    def __init__(self, wav):
        super().__init__()
        with wave.open(io.BytesIO(wav)) as source:
            if (source.getframerate(), source.getsampwidth(), source.getnchannels()) != (16000, 2, 1):
                raise ValueError("invalid_live_input_format")
            if not 1600 <= source.getnframes() <= 16000 * 26:
                raise ValueError("invalid_live_input_duration")
            self.samples = source.readframes(source.getnframes())
        self.position = 0
        self.start_time = None

    async def recv(self):
        loop = asyncio.get_running_loop()
        if self.start_time is None:
            self.start_time = loop.time()
        await asyncio.sleep(max(0, self.start_time + self.position / 16000 - loop.time()))
        raw = self.samples[self.position * 2:self.position * 2 + 640].ljust(640, b"\0")
        frame = av.AudioFrame.from_ndarray(np.frombuffer(raw, "<i2").reshape(1, -1), format="s16", layout="mono")
        frame.pts = self.position
        frame.sample_rate = 16000
        frame.time_base = Fraction(1, 16000)
        self.position += 320
        return frame


async def live_turn(client, config, headers, wav, turn_id, send, send_audio, encoder):
    if config.get("hardware_live_consent") is not True:
        raise PermissionError("hardware_live_permission_required")
    scope = {"device_id": config["device_id"], "client_id": config["device_id"]}
    base = config["brain_url"] + "/api/v1/live/sessions"
    peer = RTCPeerConnection(RTCConfiguration(iceServers=[]))
    capture = CapturedSpeech(wav)
    peer.addTrack(capture)
    tracks = []
    peer.on("track", tracks.append)
    started = attempted = False
    tasks = []
    try:
        await peer.setLocalDescription(await peer.createOffer())
        offer = dict(**scope, conversation_mode="unified", sdp=peer.localDescription.sdp, consent=True, session_id=turn_id,
                     conversation_id=config["conversation_id"], client_kind="device",
                     requested_model="gpt-live-1", personalization_mode="guest", remember=False)
        attempted = True
        reply = await client.post(base, headers=headers, json=offer)
        reply.raise_for_status()
        answer = reply.json()
        if answer.get("session_id") != turn_id or answer.get("configuration_confirmed") is not True or answer.get("model") != "gpt-live-1":
            raise ValueError("hardware_live_settings_unconfirmed")
        await peer.setRemoteDescription(RTCSessionDescription(sdp=answer["sdp"], type="answer"))
        if len(tracks) != 1 or tracks[0].kind != "audio":
            raise ValueError("hardware_live_audio_track_missing")

        async def output():
            nonlocal started
            resampler = av.AudioResampler(format="s16", layout="mono", rate=24000)
            while True:
                frame = await tracks[0].recv()
                for converted in resampler.resample(frame):
                    pcm = converted.to_ndarray()
                    if not started:
                        if np.max(np.abs(pcm.astype(np.int32))) < 8:
                            continue
                        await send({"type":"tts","state":"start"})
                        started = True
                    for packet in encoder.feed(pcm.astype("<i2").tobytes(), 24000):
                        await send_audio(packet)

        async def events():
            from spotpear_scene import project_scene
            async with client.stream("GET", f"{base}/{turn_id}/events", headers=headers, params=scope) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    event = json.loads(line[6:])
                    if event.get("session_id") != turn_id:
                        raise ValueError("unexpected_live_session")
                    kind, data = event["type"], event["data"]
                    if kind == "visual_response":
                        try:
                            scene = project_scene(data["presentation"])
                        except (KeyError, ValueError):
                            continue
                        await send(scene)
                    elif kind == "input_transcript":
                        await send({"type":"stt","text":data["text"][:512]})
                    elif kind == "closed":
                        if not data.get("final_usage_confirmed"):
                            raise ValueError("hardware_live_close_unconfirmed")
                        return data.get("mode")
            raise ValueError("hardware_live_events_interrupted")

        media = asyncio.create_task(output())
        terminal = asyncio.create_task(events())
        tasks.extend((media, terminal))
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        if media in done:
            from aiortc.mediastreams import MediaStreamError
            try:
                media.result()
            except MediaStreamError:
                # The remote track can close just before the scoped terminal event.
                pass
            await asyncio.wait_for(terminal, timeout=12)
        else:
            terminal.result()
        media.cancel()
        await asyncio.gather(media, return_exceptions=True)
        flow = terminal.result()
        if not started:
            if not (flow and flow.get("active") and flow.get("mode") == "legacy" and flow.get("provider_closed")):
                raise ValueError("hardware_live_no_audio")
            await send({"type":"tts","state":"start"})
            await send({"type":"tts","state":"sentence_start","text":"Экспертный режим"})
        else:
            for packet in encoder.finish():
                await send_audio(packet)
        await send({"type":"tts","state":"stop"})
        return flow
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        capture.stop()
        await peer.close()
        if attempted:
            # Idempotently close even on lost setup reply. Never recreate that turn.
            with suppress(Exception):
                async with asyncio.timeout(15):
                    await client.post(f"{base}/{turn_id}/command", headers=headers, json={
                        **scope, "action":"end", "command_id":uuid.uuid4().hex, "reason":"user_stop"})
