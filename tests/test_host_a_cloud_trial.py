"""Free no-network tests for 2026-11-16 HOST-A finite paid grant.

Only fake WebSocket objects, no API credentials loaded and no audio saved.
"""
import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "voice"))
from host_a_paid_budget import HostPaidTrialBudget, BudgetError, MAX_SECONDS
from host_a_cloud_transcribe import (
    CloudTranscriber, TranscriptionFault, config_update,
    _resample_16_to_24, verify_address
)
from host_wake_contract import AudioChunk, WakeEvent


def wake(end=960):
    return WakeEvent(
        stream_epoch="physical_e1", end_sample_index=end,
        phrase_id="monika", detector_id="vosk-small-ru-0.22",
        detected_monotonic_ns=1,
    )


class FakeSocket:
    def __init__(self, text="Моника сколько сейчас времени"):
        self.q = asyncio.Queue()
        self.events = []
        self.text = text

    async def send(self, payload):
        msg = json.loads(payload)
        self.events.append(msg)
        if msg["type"] == "session.update":
            await self.q.put(json.dumps({"type": "session.updated"}))
        if msg["type"] == "input_audio_buffer.commit":
            await self.q.put(json.dumps({
                "type": "input_audio_buffer.committed", "item_id": "item_1"
            }))
            await self.q.put(json.dumps({
                "type": "conversation.item.input_audio_transcription.delta",
                "item_id": "item_1", "delta": "Моника сколько"
            }))
            await self.q.put(json.dumps({
                "type": "conversation.item.input_audio_transcription.completed",
                "item_id": "item_1", "transcript": self.text
            }))

    async def recv(self):
        return await self.q.get()


class FakeContext:
    def __init__(self, ws):
        self.ws = ws

    async def __aenter__(self):
        return self.ws

    async def __aexit__(self, *a):
        return False


def test_no_session_without_real_local_monika(tmp_path):
    b = HostPaidTrialBudget(tmp_path)
    with pytest.raises(BudgetError, match="no_openai_session"):
        b.reserve("gpt-live-transcribe", 20, local_wake_confirmed=False)
    assert b.status()["sessions"] == []


def test_session_model_and_bounded_allocation(tmp_path):
    b = HostPaidTrialBudget(tmp_path)
    with pytest.raises(BudgetError, match="model_not_owner_authorized"):
        b.reserve("unexpected_paid_model", 30, local_wake_confirmed=True)
    with pytest.raises(BudgetError, match="unbounded_paid_session"):
        b.reserve("gpt-live-transcribe", 3001, local_wake_confirmed=True)
    for _ in range(16):
        b.reserve("gpt-live-1", 180, local_wake_confirmed=True)
    assert b.status()["reserved_seconds"] == 2880
    with pytest.raises(BudgetError, match="50_min_total"):
        b.reserve("gpt-live-1", 180, local_wake_confirmed=True)
    assert b.status()["reserved_estimated_usd"] <= 3


def test_conservative_reservation_survives_restart(tmp_path):
    b = HostPaidTrialBudget(tmp_path)
    ident = b.reserve("gpt-live-transcribe", 90, local_wake_confirmed=True)
    b.finish(ident, elapsed_seconds=2, result="FAILED")
    fresh = HostPaidTrialBudget(tmp_path).status()
    assert fresh["reserved_seconds"] == 90
    assert fresh["sessions"][0]["status"] == "FAILED"
    with pytest.raises(BudgetError):
        b.finish(ident, elapsed_seconds=3, result="COMPLETE")


@pytest.mark.parametrize("phrase,verdict", [
    ("Моника, сколько времени?", "CONFIRMED"),
    ("Эй, Моника, какая погода", "CONFIRMED"),
    ("монитор, сколько времени", "REJECTED"),
    ("Моник сколько времени", "REJECTED"),
    ("об Моника сколько времени", "UNCERTAIN"),
    ("сегодня говорили про Монику", "UNCERTAIN"),
    ("Моника", "UNCERTAIN"),
    ("", "UNCERTAIN"),
])
def test_cloud_name_verification(phrase, verdict):
    assert verify_address(phrase)[0] == verdict


def test_official_transcription_config_and_resampling():
    payload = config_update()
    assert payload["type"] == "session.update"
    inp = payload["session"]["audio"]["input"]
    assert inp["transcription"]["model"] == "gpt-live-transcribe"
    assert inp["turn_detection"] is None
    assert inp["format"] == {"type": "audio/pcm", "rate": 24000}
    assert len(_resample_16_to_24(bytes(960*2))) == 1440*2


def test_fake_wss_pre_roll_continuity_and_cloud_final(tmp_path):
    ws = FakeSocket()
    connects = []
    def connector(uri, **kwargs):
        connects.append((uri, kwargs))
        return FakeContext(ws)
    budget = HostPaidTrialBudget(tmp_path)
    client = CloudTranscriber(
        budget, key_loader=lambda: "sk-only-fake-for-tests",
        connector=connector
    )
    async def frames():
        yield AudioChunk(bytes(960*2), "physical_e1", 960, 10)
        yield AudioChunk(bytes(960*2), "physical_e1", 1920, 20)
    result = asyncio.run(client.transcribe(
        candidate=wake(), epoch="physical_e1",
        replay_start=0, replay_pcm16=bytes(960*2),
        next_frames=frames(), max_session_seconds=10
    ))
    assert result.verdict == "CONFIRMED"
    assert result.question == "сколько сейчас времени"
    assert result.audio_seconds == .18
    assert connects[0][0].startswith("wss://api.openai.com/v1/realtime?")
    assert [x["type"] for x in ws.events] == [
        "session.update",
        "input_audio_buffer.append",
        "input_audio_buffer.append",
        "input_audio_buffer.append",
        "input_audio_buffer.commit",
    ]
    assert budget.status()["reserved_seconds"] == 10
    assert budget.status()["sessions"][0]["status"] == "COMPLETE"


def test_wrong_epoch_fails_before_key_loading_or_budget(tmp_path):
    key_lookups = []
    b = HostPaidTrialBudget(tmp_path)
    client = CloudTranscriber(b, key_loader=lambda: key_lookups.append(1))
    async def no_frames():
        if False:
            yield None
    with pytest.raises(TranscriptionFault, match="cloud_requires_local"):
        asyncio.run(client.transcribe(
            candidate=wake(), epoch="incorrect",
            replay_start=0, replay_pcm16=bytes(1920),
            next_frames=no_frames(), max_session_seconds=10
        ))
    assert key_lookups == []
    assert b.status()["reserved_seconds"] == 0


def test_replay_gap_detected_before_paid_connection(tmp_path):
    b = HostPaidTrialBudget(tmp_path)
    client = CloudTranscriber(b, key_loader=lambda: "sk-fake")
    async def no_frames():
        if False:
            yield None
    with pytest.raises(TranscriptionFault, match="replay_position_invalid"):
        asyncio.run(client.transcribe(
            candidate=wake(), epoch="physical_e1",
            replay_start=1, replay_pcm16=bytes(1920),
            next_frames=no_frames(), max_session_seconds=10
        ))
    assert b.status()["sessions"] == []

def test_real_physical_detector_id_with_dot_is_contract_valid():
    event = wake()
    assert event.detector_id == "vosk-small-ru-0.22"
    with pytest.raises(ValueError, match="invalid_wake_identity"):
        WakeEvent("e", 1, "monika", "../bad", 1)


def test_gate_preroll_matches_trimmed_core_ring():
    import struct
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    from host_a_paid_time_trial import WakeGate
    from host_wake_core import Ring
    gate = WakeGate()
    ring = Ring()
    for n in range(50):
        frame = struct.pack("<960h", *([n + 1] * 960))
        chunk = AudioChunk(frame, "physical_e1", n * 960, n)
        event = wake((n + 1) * 960) if n == 49 else None
        gate.feed(chunk, event)
        ring.append(n * 960, frame)
    entry = gate.take()
    assert entry is not None
    event, prefix_start, replay = entry
    assert prefix_start + len(replay) // 2 == event.end_sample_index
    core_start, captured = ring.snapshot()
    assert core_start <= prefix_start
    offset = captured.find(replay[:1920], 0, 3840)
    assert offset >= 0 and offset % 2 == 0
    assert captured[offset:offset + len(replay)] == replay

def test_status_write_retries_transient_windows_reader_lock(tmp_path, monkeypatch):
    import importlib
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    pilot = importlib.import_module("host_monika_live")
    monkeypatch.setattr(pilot, "RUN", tmp_path)
    replace_original = Path.replace
    attempts = []

    def transient_lock(file, destination):
        attempts.append(1)
        if len(attempts) <= 2:
            raise PermissionError(13, "Windows temporary shared-file reader lock")
        return replace_original(file, destination)

    monkeypatch.setattr(Path, "replace", transient_lock)
    pilot.write_status({"running": True, "sample_count": 42})
    assert len(attempts) == 3
    assert json.loads((tmp_path / "status.json").read_text())["sample_count"] == 42


def test_status_write_persistent_denial_does_not_kill_audio_owner(tmp_path, monkeypatch):
    import importlib
    pilot = importlib.import_module("host_monika_live")
    monkeypatch.setattr(pilot, "RUN", tmp_path)

    def locked(file, destination):
        raise PermissionError(13, "Persistent Windows file reader lock")

    monkeypatch.setattr(Path, "replace", locked)
    pilot.write_status({"running": True})
    # Best effort diagnostic telemetry: absence of status must not abort WSS/COM3.
    assert not (tmp_path / "status.json").exists()

def test_local_time_in_ram_cache_same_minute_no_second_synthesis():
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    from host_a_time_cache import TimeAnswerCache
    now = datetime(2026, 11, 16, 23, 38, 30,
                   tzinfo=ZoneInfo("America/Sao_Paulo"))
    generated = []
    def fake_synth(voice, *, text):
        generated.append(text)
        return (str(text).encode(),)
    cache = TimeAnswerCache("private-test-voice", synth=fake_synth,
                            clock=lambda: now, ahead_minutes=3)
    cache.warm()
    assert len(generated) == 3
    packets, hit = cache.get()
    assert hit is True and packets
    assert len(generated) == 3
    now += timedelta(minutes=1)
    future_packets, hit = cache.get()
    assert hit is True and packets != future_packets
    assert len(generated) == 3


def test_time_audio_cache_never_replies_with_stale_minute():
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    from host_a_time_cache import TimeAnswerCache
    now = datetime(2026, 11, 16, 23, 59,
                   tzinfo=ZoneInfo("America/Sao_Paulo"))
    texts = []
    def fake_synth(voice, *, text):
        texts.append(text)
        return (text.encode("utf-8"),)
    cache = TimeAnswerCache("private-test-voice", synth=fake_synth,
                            clock=lambda: now, ahead_minutes=2)
    cache.warm()
    assert cache.stats()["prepared"] == 2
    now += timedelta(minutes=1)
    midnight, cached = cache.get()
    assert cached is True
    assert b"0:00" in midnight[0]
    now += timedelta(minutes=3)
    current, cached = cache.get()
    assert cached is False
    assert b"0:03" in current[0]
