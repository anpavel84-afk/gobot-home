"""Explicit free HOST output fixture over the existing 24 kHz Opus media format.

This is NOT AI speech, a model response, an acoustic measurement, or a
production launcher. No I/O except in-memory local PCM -> Opus conversion.
"""
from __future__ import annotations

import math
import struct

OUTPUT_RATE = 24000
OUTPUT_FRAME_SAMPLES = 1440
FIXTURE_FRAMES = 6
MAX_OUTPUT_PACKET_BYTES = 4096


def fixture_packets() -> tuple[bytes, ...]:
    """Short low-level 660 Hz signal with fades. Reuse the installed encoder."""
    from gobot_device_gateway import OpusOutput

    samples = OUTPUT_FRAME_SAMPLES * FIXTURE_FRAMES
    pcm = bytearray(samples * 2)
    try:
        for index in range(samples):
            position = index / samples
            envelope = min(1.0, position * 25, (1.0 - position) * 25)
            value = int(2200 * max(0.0, envelope) *
                        math.sin(2 * math.pi * 660 * index / OUTPUT_RATE))
            struct.pack_into("<h", pcm, index * 2, value)
        encoder = OpusOutput()
        packets = encoder.feed(bytes(pcm), OUTPUT_RATE)
        packets.extend(encoder.finish())
        if (not FIXTURE_FRAMES <= len(packets) <= FIXTURE_FRAMES + 2 or
                any(not 0 < len(p) <= MAX_OUTPUT_PACKET_BYTES for p in packets)):
            raise ValueError("unexpected_fixture_packetization")
        return tuple(packets)
    finally:
        pcm[:] = bytes(len(pcm))
