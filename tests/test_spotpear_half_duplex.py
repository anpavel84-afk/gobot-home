"""Free state/peer/codec fixtures, not human acoustic or provider acceptance."""
import asyncio,sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'services/voice'))
from spotpear_half_duplex import HalfDuplex

def speaking():
    s=HalfDuplex();s.listen();assert s.input_open
    assert s.commit() and not s.input_open
    s.response('r1');s.packet(1.)
    return s

def test_generation_end_and_host_empty_do_not_open_microphone():
    s=speaking();s.provider_done('r1',generation=True,drained=True)
    assert not s.drain(10,queues_empty=True) and not s.input_open
    s.activity(True,11);s.activity(False,12)
    s.activity(False,12.05) # Repeated idle heartbeats must not postpone the guard forever.
    assert not s.drain(12.1,queues_empty=True)
    assert not s.drain(13,queues_empty=False)
    assert s.drain(13,queues_empty=True)
    s.listen();assert s.input_open

def test_late_packet_invalidates_previous_drain_ack_and_old_response_events():
    s=speaking();s.provider_done('r1',generation=True,drained=True)
    s.activity(True,2);s.activity(False,3);s.packet(4)
    assert not s.drain(10,queues_empty=True)
    s.activity(False,5);assert s.drain(6,queues_empty=True)
    s.listen();s.commit();s.response('r2');s.packet(7)
    s.provider_done('r1',generation=True,drained=True);s.activity(False,8)
    assert not s.drain(10,queues_empty=True)

def test_stop_and_duplicate_commit_do_not_restart_listening():
    s=speaking();assert not s.commit()
    s.stop();assert not s.input_open
    with pytest.raises(ValueError):s.listen()
    with pytest.raises(ValueError):s.packet(10)

def test_gated_capture_keeps_quiet_speech_but_discards_speaker_echo():
    import av,numpy as np
    from fractions import Fraction
    from spotpear_realtime import GatedCapture
    class Capture:
        count=0
        async def recv(self):
            self.count+=1
            frame=av.AudioFrame.from_ndarray(np.full((1,320),2,dtype=np.int16),format='s16',layout='mono')
            frame.sample_rate=16000;frame.pts=self.count*320;frame.time_base=Fraction(1,16000);return frame
    async def run():
        s=HalfDuplex();source=Capture();gate=GatedCapture(source,s)
        assert not (await gate.recv()).to_ndarray().any()
        s.listen();assert (await gate.recv()).to_ndarray().min()==2
        s.commit();assert not (await gate.recv()).to_ndarray().any()
        assert source.count==3
    asyncio.run(run())

def test_nonclosing_opus_silence_flush_preserves_second_answer():
    import numpy as np
    from gobot_device_gateway import OpusOutput
    encoder=OpusOutput()
    pcm=(np.sin(np.arange(1600)/12)*2000).astype('<i2').tobytes()
    first=encoder.feed(pcm,24000)+encoder.feed(bytes(2880),24000)
    assert first and not encoder.closed
    second=encoder.feed(pcm,24000)+encoder.feed(bytes(2880),24000)
    assert second and not encoder.closed
    encoder.finish()
