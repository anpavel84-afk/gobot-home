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


class StreamingSpeech(AudioStreamTrack):
    """Bounded 16 kHz PCM during connection setup; never wait for end of speech."""
    # Ten seconds for the complete connection setup, plus two seconds of scheduling margin.
    # This is a hard RAM cap, not a new recording/end-of-utterance step.
    MAX_BACKLOG_BYTES = 16000 * 2 * 12
    def __init__(self):
        super().__init__()
        self.buffer = bytearray()
        self.position = 0
        self.next_frame = None
        self.finished = False
        self.playing = False
        self.input_seen = False
        self.ended = asyncio.Event()
        self.last_signal = 0.
        self.created_at = asyncio.get_running_loop().time()
        self.received_samples = 0
        self.consumed_samples = 0
        self.peak_backlog_bytes = 0
        self.phase = "waiting"

    def feed(self, pcm):
        if self.finished or len(pcm)%2 or len(self.buffer)+len(pcm)>self.MAX_BACKLOG_BYTES:
            raise ValueError("hardware_input_backlog_or_state")
        self.buffer.extend(pcm)
        self.received_samples += len(pcm)//2
        self.peak_backlog_bytes = max(self.peak_backlog_bytes, len(self.buffer))
        self.input_seen |= bool(pcm)
        if pcm and np.sqrt(np.mean(np.frombuffer(pcm,"<i2").astype(np.float64)**2))>=100:
            self.last_signal=asyncio.get_running_loop().time()

    def finish(self):
        self.finished = True
        if not self.buffer:
            self.ended.set()

    def diagnostics(self):
        return {"phase": self.phase, "received_samples": self.received_samples,
                "consumed_samples": self.consumed_samples, "clocked_samples": self.position,
                "backlog_ms": len(self.buffer)//32, "peak_backlog_ms": self.peak_backlog_bytes//32,
                "age_ms":round((asyncio.get_running_loop().time()-self.created_at)*1000),
                "finished": self.finished}

    async def recv(self):
        loop = asyncio.get_running_loop()
        if self.next_frame is None:
            self.next_frame = loop.time()
        await asyncio.sleep(max(0, self.next_frame-loop.time()))
        raw = bytes(self.buffer[:640])
        del self.buffer[:640]
        self.consumed_samples += len(raw)//2
        if self.finished and not self.buffer:
            self.ended.set()
        frame = av.AudioFrame.from_ndarray(np.frombuffer(raw.ljust(640, bytes(1)),"<i2").reshape(1,-1),
                                           format="s16",layout="mono")
        frame.pts = self.position
        frame.time_base = Fraction(1,16000)
        frame.sample_rate = 16000
        self.position += 320
        self.next_frame = max(self.next_frame+.02,loop.time())
        return frame


async def live_turn(client, config, headers, wav, turn_id, send, send_audio, encoder):
    if config.get("hardware_live_consent") is not True:
        raise PermissionError("hardware_live_permission_required")
    scope = {"device_id": config["device_id"], "client_id": config["device_id"]}
    base = config["brain_url"] + "/api/v1/live/sessions"
    peer = RTCPeerConnection(RTCConfiguration(iceServers=[]))
    capture = wav if isinstance(wav,StreamingSpeech) else CapturedSpeech(wav)
    continuous = config.get("continuous_live") is True
    relay = None
    if continuous:
        if not isinstance(capture, StreamingSpeech) or not config.get("livekit_settings"):
            raise ValueError("continuous_live_requires_livekit")
        from spotpear_livekit import LocalMediaRelay
        relay=LocalMediaRelay(config["livekit_settings"],turn_id)
    tracks = []
    peer.on("track", tracks.append)
    started = attempted = False
    tasks = []
    async def setup():
        nonlocal attempted
        if relay:
            capture.phase="relay_connect"
            await relay.connect()
            async def delivered(pcm):
                for packet in encoder.feed(pcm,24000):
                    await send_audio(packet)
            tasks.append(relay.task(relay.output(delivered)))
            tasks.append(asyncio.ensure_future(relay.error))
        peer.addTrack(relay.input_track if relay else capture)
        if isinstance(capture,StreamingSpeech):capture.phase="offer"
        await peer.setLocalDescription(await peer.createOffer())
        offer = dict(**scope, conversation_mode="unified", sdp=peer.localDescription.sdp, consent=True, session_id=turn_id,
                     conversation_id=config["conversation_id"], client_kind="device",
                     requested_model="gpt-live-1", personalization_mode="guest", remember=False)
        attempted = True
        if isinstance(capture,StreamingSpeech):capture.phase="brain_setup"
        reply = await client.post(base, headers=headers, json=offer)
        reply.raise_for_status()
        answer = reply.json()
        if answer.get("session_id") != turn_id or answer.get("configuration_confirmed") is not True or answer.get("model") != "gpt-live-1":
            raise ValueError("hardware_live_settings_unconfirmed")
        if isinstance(capture,StreamingSpeech):capture.phase="transport_connect"
        await peer.setRemoteDescription(RTCSessionDescription(sdp=answer["sdp"], type="answer"))
        if len(tracks) != 1 or tracks[0].kind != "audio":
            raise ValueError("hardware_live_audio_track_missing")
        if relay:
            tasks.append(relay.task(relay.microphone(capture, wait_for_transport=True)))
            await relay.input_track.started.wait()
        if isinstance(capture,StreamingSpeech):capture.phase="streaming"

    try:
        if continuous:
            # Bound the entire setup, not just the HTTP request. Preserve the first
            # syllables while connecting, without waiting for the whole question.
            async with asyncio.timeout_at(capture.created_at+10):
                await setup()
        else:
            await setup()

        def loop_time(): return asyncio.get_running_loop().time()
        async def activity():
            while True:
                command = dict(**scope,action="activity",command_id=uuid.uuid4().hex,
                               input_active=(loop_time()-capture.last_signal<.5) if continuous else capture.input_seen and not capture.ended.is_set(),
                               playback_active=capture.playing)
                response = await client.post(f"{base}/{turn_id}/command",headers=headers,json=command)
                response.raise_for_status()
                await asyncio.sleep(.65)

        if isinstance(capture,StreamingSpeech):
            tasks.append(asyncio.create_task(activity()))
        answer_has_audio = asyncio.Event()
        question_transcribed = asyncio.Event()
        if isinstance(capture, StreamingSpeech) and not continuous:
            async def provider_end_signal():
                await question_transcribed.wait()
                await answer_has_audio.wait()
                if not capture.finished:
                    await send({"type":"gobot_input_end"})
                # Keep task lifetime bound to the turn, not its first output.
                await asyncio.Future()
            tasks.append(asyncio.create_task(provider_end_signal()))
        last_sound = [0.]
        resampler = av.AudioResampler(format="s16", layout="mono", rate=24000)
        async def output():
            nonlocal started
            while True:
                frame = await tracks[0].recv()
                for converted in resampler.resample(frame):
                    pcm = converted.to_ndarray()
                    now = asyncio.get_running_loop().time()
                    if np.max(np.abs(pcm.astype(np.int32))) >= 8:
                        last_sound[0] = now
                    elif not started or now - last_sound[0] > .30:
                        continue
                    if not started:
                        if isinstance(capture, StreamingSpeech) and not continuous:
                            answer_has_audio.set()
                            await asyncio.wait_for(capture.ended.wait(), timeout=26)
                        await send({"type":"tts","state":"start"})
                        started = True
                    raw=pcm.astype("<i2").tobytes()
                    if relay: await relay.send_speaker(raw)
                    else:
                        for packet in encoder.feed(raw,24000):await send_audio(packet)

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
                        if data["text"].strip():
                            question_transcribed.set()
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
        for task in done:
            if task not in (media,terminal):
                task.result()
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
            # A terminal control event can precede RTP still in the jitter buffer.
            # Only after this event can sustained trailing silence end transport drain.
            loop=asyncio.get_running_loop()
            arrived=loop.time()
            while not media.done() and loop.time()-max(arrived,last_sound[0])<.45:
                if loop.time()-arrived>3:
                    raise ValueError("hardware_live_media_drain_unconfirmed")
                await asyncio.sleep(.02)
        media.cancel()
        await asyncio.gather(media, return_exceptions=True)
        flow = terminal.result()
        if not started:
            if not (flow and flow.get("active") and flow.get("mode") == "legacy" and flow.get("provider_closed")):
                raise ValueError("hardware_live_no_audio")
            await send({"type":"tts","state":"start"})
            await send({"type":"tts","state":"sentence_start","text":"Экспертный режим"})
        else:
            for frame in resampler.resample(None):
                for packet in encoder.feed(frame.to_ndarray().astype("<i2").tobytes(), 24000):
                    await send_audio(packet)
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
        if relay: await relay.close()
        if attempted:
            # Idempotently close even on lost setup reply. Never recreate that turn.
            with suppress(Exception):
                async with asyncio.timeout(15):
                    await client.post(f"{base}/{turn_id}/command", headers=headers, json={
                        **scope, "action":"end", "command_id":uuid.uuid4().hex, "reason":"user_stop"})
