"""Synthetic PCM only: capture-clock continuity/privacy, never acoustic claims."""
import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'services/voice'))
from sophia_audio import PcmRing, OrderedOpus, ContinuousPcm24, AudioContinuityError


def meta(frame, *, epoch='capture-1', start=None):
    return {'stream_epoch': epoch, 'frame_id': frame,
            'sample_start': frame*960 if start is None else start, 'sample_count': 960}


def pcm(frame):
    return struct.pack('<960h', *[(frame*960+i)%30000 for i in range(960)])


def wake(position, *, ident='wake-1', epoch='capture-1'):
    return {'stream_epoch': epoch, 'wake_id': ident,
            'detector_sample': position, 'detector_monotonic_us': 123456}


def test_one_cursor_bursts_history_then_live_without_duplicates():
    ring = PcmRing()
    ring.reset('capture-1')
    for i in range(30):
        ring.append(meta(i), pcm(i))
    assert ring.begin(wake(25000))
    start = 9000
    parts = ring.read_available(max_samples=4000)
    got = b''.join(raw for _, raw in parts)
    original = b''.join(pcm(i) for i in range(30))
    assert parts[0][0] == start and got == original[start*2:]
    assert not ring.read_available()
    ring.append(meta(30), pcm(30))
    assert ring.read_available() == [(28800, pcm(30))]
    assert not ring.begin(wake(25000))  # Exact replay never starts a second turn.
    ring.acknowledge_sent(29760)
    event = next(e for e in ring.events if e['event'] == 'pre_roll_flushed')
    assert event['receipt'] == 'client_send_completed_not_provider_ack'


def test_wake_before_matching_packet_waits_and_keeps_first_words():
    ring = PcmRing()
    ring.reset('capture-1')
    for i in range(4):
        ring.append(meta(i), pcm(i))
    ring.begin(wake(4500))
    assert ring.read_available() == []
    ring.append(meta(4), pcm(4))
    data = b''.join(raw for _, raw in ring.read_available())
    assert data == b''.join(pcm(i) for i in range(5))


def test_long_input_larger_than_ring_is_not_cut_off():
    ring = PcmRing(seconds=1)
    ring.reset('capture-1')
    ring.begin(wake(0), pre_roll_seconds=0)
    received = bytearray()
    for i in range(1200):  # 72 seconds input, one-second history.
        ring.append(meta(i), pcm(i))
        received.extend(b''.join(raw for _, raw in ring.read_available()))
    assert len(received) == 1200*1920
    assert ring.cursor.sent_samples == 1200*960
    assert sum(block.sample_count for block in ring.blocks) <= 16000


def test_real_overrun_is_explicit_not_silently_skipped():
    ring = PcmRing(seconds=1)
    ring.reset('capture-1')
    ring.begin(wake(0), pre_roll_seconds=0)
    with pytest.raises(AudioContinuityError, match='overrun'):
        for i in range(20):
            ring.append(meta(i), pcm(i))
    assert ring.cursor is None
    assert any(e['event'] == 'input_overrun' for e in ring.events)


def test_duplicate_is_rejected_before_opus_decoder_advances():
    class Decoder:
        def __init__(self):
            self.calls = 0
        def feed(self, data):
            self.calls += 1
            return data
        def close(self):
            pass
    ring = PcmRing()
    stream = OrderedOpus(ring, Decoder)
    stream.reset('capture-1')
    assert stream.feed(meta(0), pcm(0))
    assert not stream.feed(meta(0), pcm(0))
    assert stream.decoder.calls == 1
    with pytest.raises(AudioContinuityError, match='frame_gap'):
        stream.feed(meta(2), pcm(2))
    assert stream.decoder.calls == 1


def test_different_epochs_never_glue():
    ring = PcmRing()
    ring.reset('capture-1')
    ring.append(meta(0), pcm(0))
    with pytest.raises(AudioContinuityError, match='epoch'):
        ring.append(meta(1, epoch='capture-2'), pcm(1))
    with pytest.raises(AudioContinuityError, match='epoch'):
        ring.begin(wake(500, epoch='capture-2'))
    ring.reset('capture-2')
    assert not ring.blocks and ring.cursor is None and ring.end == 0


@pytest.mark.parametrize('reason', ['mute', 'playback'])
def test_forbidden_intervals_cannot_leak_through_preroll(reason):
    ring = PcmRing()
    ring.reset('capture-1')
    ring.append(meta(0), pcm(0))
    ring.set_blocked(True, reason=reason)
    for i in range(1, 8):
        ring.append(meta(i), pcm(i))
    assert not ring.blocks
    with pytest.raises(PermissionError):
        ring.begin(wake(7680))
    ring.set_blocked(False, reason=reason)
    for i in range(8, 10):
        ring.append(meta(i), pcm(i))
    ring.begin(wake(9000))
    assert b''.join(raw for _, raw in ring.read_available()) == pcm(8)+pcm(9)


def test_stateful_resampling_is_chunk_invariant_and_keeps_duration():
    original = b''.join(pcm(i) for i in range(40))
    whole = ContinuousPcm24()
    expected = whole.feed(original)+whole.finish()
    split = ContinuousPcm24()
    actual = b''.join(split.feed(pcm(i)) for i in range(40))+split.finish()
    assert actual == expected
    assert len(actual)//2 == 40*960*3//2


def test_future_playback_floor_never_regresses_as_delayed_frames_arrive():
    ring = PcmRing()
    ring.reset('capture-1')
    ring.append(meta(0), pcm(0))
    ring.set_blocked(True, sample_floor=5000, reason='playback')
    ring.append(meta(1), pcm(1))
    assert ring.floor == 5000
    ring.set_blocked(False, reason='guard')
    ring.begin(wake(5000), pre_roll_seconds=0)
    for i in range(2, 6):
        ring.append(meta(i), pcm(i))
    got = b''.join(data for _, data in ring.read_available())
    all_pcm = b''.join(pcm(i) for i in range(6))
    assert got == all_pcm[5000*2:]
