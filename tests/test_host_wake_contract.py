"""HOST-B contract acceptance in pure free local memory, never a paid session."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "voice"))
from host_wake_contract import AudioChunk, WakeEvent, CONTRACT_VERSION, SAMPLE_RATE
from host_wake_core import HostCore, StreamFault

PCM = bytes(1920)


def frame(seq, epoch="e"):
    return {"epoch": epoch, "seq": seq, "sample_start": seq * 960,
            "sample_count": 960}


class Detector:
    def __init__(self, *, end=None, epoch=None):
        self.chunks = []
        self.end = end
        self.epoch = epoch
        self.reset_count = 0

    def feed_chunk(self, chunk):
        self.chunks.append(chunk)
        if chunk.sample_index == 960:
            return WakeEvent(
                self.epoch or chunk.stream_epoch,
                self.end if self.end is not None else chunk.sample_index + 480,
                "gobot", "host-b-fixture", chunk.received_monotonic_ns + 1,
                confidence=0.9)
        return None

    def reset(self):
        self.reset_count += 1


def test_interface_is_pcm_16k_and_v1():
    assert CONTRACT_VERSION == 1 and SAMPLE_RATE == 16000
    chunk = AudioChunk(PCM, "epoch_1", 960, 1_234_000)
    assert chunk.end_sample_index == 1920
    assert chunk.sample_index == 960
    assert not hasattr(chunk, "opus") and not hasattr(chunk, "transcript")


@pytest.mark.parametrize("change", [
    {"pcm_s16le": b""}, {"pcm_s16le": b"x"},
    {"pcm_s16le": bytes(1922)}, {"pcm_s16le": bytearray(1920)},
    {"stream_epoch": ""}, {"stream_epoch": "../bad"},
    {"sample_index": True}, {"sample_index": -1},
    {"received_monotonic_ns": 1.5}, {"received_monotonic_ns": -1},
])
def test_invalid_chunks_fail_closed(change):
    with pytest.raises(ValueError):
        AudioChunk(**({"pcm_s16le": PCM, "stream_epoch": "e",
                        "sample_index": 0, "received_monotonic_ns": 1} | change))


@pytest.mark.parametrize("change", [
    {"stream_epoch": ""}, {"phrase_id": ""}, {"detector_id": "../bad"},
    {"end_sample_index": True}, {"end_sample_index": -1},
    {"detected_monotonic_ns": True}, {"detected_monotonic_ns": -1},
    {"confidence": float("nan")}, {"confidence": 2.0},
    {"confidence": -0.1}, {"confidence": True},
])
def test_invalid_wake_event_fail_closed(change):
    with pytest.raises(ValueError):
        WakeEvent(**({"stream_epoch": "e", "end_sample_index": 1,
                       "phrase_id": "gobot", "detector_id": "fixture",
                       "detected_monotonic_ns": 2} | change))


def test_host_b_contract_receives_original_frames_and_prefix_once():
    d = Detector()
    c = HostCore(d, "e")
    assert c.feed(frame(0), PCM, received_monotonic_ns=1_000_000) == []
    result = c.feed(frame(1), PCM, received_monotonic_ns=1_060_000)
    assert result and result[0]["source"] == "host_wake"
    assert [(x.stream_epoch, x.sample_index, x.received_monotonic_ns)
            for x in d.chunks] == [("e", 0, 1_000_000), ("e", 960, 1_060_000)]
    assert c.feed(frame(2), PCM) == []
    capture = c.finish_input()
    assert (capture.start, capture.cursor, len(capture.pcm)) == (0, 2880, 5760)
    capture.clear()
    c.close()


@pytest.mark.parametrize("end,epoch", [(2500, "e"), (480, "wrong")])
def test_host_b_stale_event_fails_closed(end, epoch):
    c = HostCore(Detector(end=end, epoch=epoch), "e")
    c.feed(frame(0), PCM)
    with pytest.raises(StreamFault, match="stale_or_replayed_wake_event"):
        c.feed(frame(1), PCM)
    c.close()


def test_replayed_wake_after_input_finish_rejected():
    c = HostCore(Detector(), "e")
    c.feed(frame(0), PCM)
    c.feed(frame(1), PCM)
    capture = c.finish_input()
    capture.clear()
    # A broken HOST-B detector must not re-fire the same historic phrase.
    class Replay:
        def reset(self): pass
        def feed_chunk(self, chunk):
            return WakeEvent("e", 1440, "gobot", "bad-replay", 1)
    c.detector = Replay()
    with pytest.raises(StreamFault, match="stale_or_replayed_wake_event"):
        c.feed(frame(2), PCM)
    c.close()


def test_new_epoch_is_independent_and_never_reuses_previous_history():
    first = HostCore(Detector(), "epoch_A")
    first.feed(frame(0, "epoch_A"), PCM)
    first.close()
    second = HostCore(Detector(), "epoch_B")
    assert second.feed(frame(0, "epoch_B"), PCM) == []
    assert second.history.size == 960
    with pytest.raises(StreamFault, match="stale_transport_epoch"):
        second.feed(frame(1, "epoch_A"), PCM)
    second.close()
