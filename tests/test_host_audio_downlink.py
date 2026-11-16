"""No-cost, fully local Opus duplex test. Fake device, never actual Spotpear."""
import asyncio
import json
import sys
from pathlib import Path

import av
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "voice"))
from host_downlink import FIXTURE_FRAMES, fixture_packets
from host_stream import HostConnection, StreamFault
from gobot_device_gateway import Gateway, OpusOutput, validate_hello


class QuietDetector:
    def reset(self):
        pass

    def feed(self, pcm, *, speaking):
        return None


HELLO = {
    "type": "hello", "version": 1, "transport": "websocket",
    "audio_params": {"format": "opus", "sample_rate": 16000,
                     "channels": 1, "frame_duration": 60},
    "host_stream": {"version": 1, "capture": "continuous",
                    "frame_sequence": True, "local_wake_enabled": False,
                    "local_feedback": True, "playback_epoch": True},
}


def uplink_packets(n):
    # Use the actual 16 kHz input encoder, not the 24 kHz output codec.
    import numpy as np
    from fractions import Fraction
    codec = av.CodecContext.create("libopus", "w")
    codec.sample_rate = 16000
    codec.layout = "mono"
    codec.format = "s16"
    codec.time_base = Fraction(1, 16000)
    codec.options = {"frame_duration": "60", "application": "voip"}
    codec.open()
    output = []
    for index in range(n):
        frame = av.AudioFrame.from_ndarray(np.zeros((1, 960), dtype=np.int16),
                                           format="s16", layout="mono")
        frame.sample_rate = 16000
        frame.time_base = Fraction(1, 16000)
        frame.pts = index * 960
        output.extend(bytes(packet) for packet in codec.encode(frame))
    # No final encoder flush: a continuous microphone never sends an EOF tail.
    assert len(output) == n
    return output


def test_fixture_is_existing_opus_24k_not_a_paid_answer():
    frames = fixture_packets()
    assert FIXTURE_FRAMES <= len(frames) <= FIXTURE_FRAMES + 2
    assert all(0 < len(x) <= 4096 for x in frames)
    decoder = av.CodecContext.create("opus", "r")
    decoder.extradata = (b"OpusHead\x01\x01\x00\x00" +
                         (24000).to_bytes(4, "little") + b"\x00\x00\x00")
    decoder.open()
    decoded = [frame for packet in frames for frame in decoder.decode(av.Packet(packet))]
    assert decoded and sum(x.samples / x.sample_rate for x in decoded) >= .36


def test_local_authenticated_full_duplex_fixture_not_provider():
    from websockets.asyncio.server import serve
    from websockets.asyncio.client import connect

    async def main():
        gateway = []
        calls = []

        def forbidden(*args, **kwargs):
            calls.append(True)
            raise AssertionError("paid provider forbidden")

        config = {"device_mac": "test-mac", "device_token": "test-token",
                  "mode": "realtime_b", "host_wake": {
                      "enabled": True, "lan_stream_consent": True,
                      "acceptance_only": True, "free_downlink_fixture": True}}

        async def handler(ws):
            g = Gateway(config, "fixture-only", client_factory=forbidden,
                        host_detector_factory=QuietDetector)
            g.save_stats = lambda: None
            g.reserve_manual_turn = forbidden
            g.respond = forbidden
            gateway.append(g)
            await g.handle(ws)

        async with serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            async with connect(f"ws://127.0.0.1:{port}/xiaozhi/v1/",
                               additional_headers={
                                   "Device-Id": "test-mac", "Protocol-Version": "1",
                                   "Authorization": "Bearer test-token"}) as ws:
                send_lock = asyncio.Lock()
                async def send(message, packet=None):
                    async with send_lock:
                        await ws.send(json.dumps(message))
                        if packet is not None:
                            await ws.send(packet)

                await ws.send(json.dumps(HELLO))
                hello = json.loads(await ws.recv())
                ready = json.loads(await ws.recv())
                assert hello["audio_params"]["sample_rate"] == 24000
                assert ready["paid_session_opened"] is False
                epoch, session = ready["epoch"], ready["session_id"]
                def message(type, **kw):
                    return {"type": type, "epoch": epoch, "session_id": session, **kw}

                await send(message("gobot_host_ready_ack", frame_samples=960))
                await send(message("gobot_host_fixture"))

                async def continuous_mic():
                    for seq, packet in enumerate(uplink_packets(14)):
                        await send(message("gobot_host_frame", seq=seq,
                                           sample_start=seq * 960,
                                           sample_count=960), packet)
                        await asyncio.sleep(.060)

                mic_task = asyncio.create_task(continuous_mic())
                seen = []
                playback_id = None
                inside = False
                packet_count = None
                async with asyncio.timeout(6):
                    while True:
                        control = json.loads(await ws.recv())
                        kind = control["type"]
                        if kind == "gobot_host_output_start":
                            assert control["audio_kind"] == "fixture"
                            assert control["output_epoch"] == 0
                            playback_id = control["playback_id"]
                            packet_count = control["packet_count"]
                            inside = True
                        elif kind == "gobot_host_output_frame":
                            assert inside and control["playback_id"] == playback_id
                            assert control["seq"] == len(seen)
                            assert control["sample_start"] == len(seen) * 1440
                            packet = await ws.recv()
                            assert isinstance(packet, bytes)
                            seen.append(packet)
                            if len(seen) == 1:
                                await send(message("gobot_host_playback",
                                                   playing=True, output_epoch=0,
                                                   playback_id=playback_id))
                        elif kind == "gobot_host_output_end":
                            assert control["packet_count"] == packet_count == len(seen)
                            await send(message("gobot_host_playback", playing=False,
                                               output_epoch=0, playback_id=playback_id))
                            break
                        else:
                            raise AssertionError(f"unapproved downlink: {kind}")
                await mic_task
                await asyncio.sleep(.12)
                await send(message("gobot_host_mute", muted=True))
                await ws.wait_closed()

        assert FIXTURE_FRAMES <= len(seen) <= FIXTURE_FRAMES + 2 and len(gateway) == 1 and not calls
        s = gateway[0].stats["host"]
        assert s["provider_calls"] == s["financial_reservations"] == 0
        assert s["received_packets"] == 14 and s["downlink_packets"] == len(seen)
        assert s["fixture_playback_started_ack"] is True
        assert s["fixture_playback_drained_ack"] is True
        assert s["max_queue_frames"] <= 4 and s["raw_audio_saved"] is False
        assert s["clean_mute"] is True
        assert "last_failure_code" not in s, s

    asyncio.run(main())


def test_fixture_default_disabled():
    class Disabled:
        pass
    h = HostConnection(QuietDetector)
    assert not h.allow_free_fixture and not h.fixture_requested


@pytest.mark.parametrize("controls,allow,expected", [
    (["gobot_host_fixture"], False, "fixture_request_forbidden"),
    (["gobot_host_fixture", "gobot_host_fixture"], True, "fixture_request_forbidden"),
    (["gobot_host_playback"], True, "unknown_playback_id"),
])
def test_fixture_access_and_replay_fails_closed(controls, allow, expected):
    """No device, no paid API; reject unauthorized/replayed control events."""
    from types import SimpleNamespace

    class Device:
        def __init__(self):
            self.stage = 0
            self.sent = []
            self.epoch = None
            self.session = None
            self.closed = False

        async def send(self, raw):
            if isinstance(raw, bytes):
                self.sent.append(raw)
                return
            obj = json.loads(raw)
            self.sent.append(obj)
            self.epoch = obj["epoch"]
            self.session = obj["session_id"]

        async def recv(self):
            await asyncio.sleep(.002)
            if self.stage == 0:
                self.stage = 1
                return json.dumps(HELLO)
            if self.stage == 1:
                self.stage = 2
                return json.dumps({
                    "type": "gobot_host_ready_ack", "epoch": self.epoch,
                    "session_id": self.session, "frame_samples": 960})
            index = self.stage - 2
            if index < len(controls):
                self.stage += 1
                kind = controls[index]
                data = {"type": kind, "epoch": self.epoch,
                        "session_id": self.session}
                if kind == "gobot_host_playback":
                    data.update(playing=True, output_epoch=0,
                                playback_id="unknown")
                return json.dumps(data)
            await asyncio.Event().wait()

        async def close(self, code, reason):
            self.closed = True

    async def run():
        d = Device()
        h = HostConnection(QuietDetector, allow_free_fixture=allow)
        await h.run(d, validate_hello)
        assert d.closed and h.stats["last_failure_code"] == expected, h.stats
        assert h.stats["provider_calls"] == 0
        assert h.last_core.closed and h.last_core.history.size == 0

    asyncio.run(run())
