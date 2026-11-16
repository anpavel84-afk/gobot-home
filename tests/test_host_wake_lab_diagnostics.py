"""Diagnostics are read-only and never equate model finals with early wake."""
import io
import tempfile
import unittest
import wave
from pathlib import Path

from services.voice.host_wake_lab.detect import Hypothesis, WakeLab
from services.voice.host_wake_lab.gobi_diagnostics import (
    audit_pcm_file, replay_model_hypotheses, get_final_hypothesis,
)


class FakeRecognizer:
    detector_id = "fake-gobi"
    def __init__(self):
        self.count=0
    def reset(self):
        self.count=0
    def feed_pcm(self,pcm):
        self.count+=1
        return Hypothesis("гоби какая погода" if self.count>1 else "го",
                          updated=True)


class AudioDiagnosticTests(unittest.TestCase):
    def test_canonical_format_hash_and_peak(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/"synthetic.wav"
            with wave.open(str(p),"wb") as w:
                w.setframerate(16000)
                w.setnchannels(1)
                w.setsampwidth(2)
                w.writeframes(b"\x00\x00"*16000)
            result=audit_pcm_file(p)
            self.assertEqual(result["sample_rate"],16000)
            self.assertEqual(result["bits_per_sample"],16)
            self.assertEqual(result["duration_s"],1.0)
            self.assertEqual(len(result["sha256"]),64)
            self.assertFalse(result["pronunciation_stress_acoustically_verified"])

    def test_wrong_audio_header_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/"mono_8k.wav"
            with wave.open(str(p),"wb") as w:
                w.setframerate(8000)
                w.setnchannels(1)
                w.setsampwidth(2)
                w.writeframes(b"\x00\x00"*100)
            with self.assertRaises(ValueError):
                audit_pcm_file(p)

    def test_decoder_raw_updates_not_wake_and_not_saved(self):
        lines=[]
        result=replay_model_hypotheses(
            FakeRecognizer(),b"\x00\x00"*960*3,
            label="FAKE_TEST",tail_silence_s=0,
            output=lambda *a:lines.append(a))
        self.assertGreaterEqual(result["updates_observed"],2)
        self.assertFalse(result["hypotheses_persisted"])
        self.assertFalse(result["pcm_saved"])
        self.assertTrue(any("PARTIAL" in v for l in lines for v in l
                            if isinstance(v,str)))
        self.assertEqual(result["stage"],"UNKNOWN_BACKEND_NO_FINAL")

    def test_wake_module_retains_last_model_hypothesis_in_memory_only(self):
        l=WakeLab(FakeRecognizer())
        l.feed(pcm_s16le=b"\0\0"*960,stream_epoch="e",
               sample_index=0,received_monotonic_ns=100)
        self.assertEqual(l.last_hypothesis.text,"го")
        l.reset()
        self.assertIsNone(l.last_hypothesis)


if __name__=="__main__":
    unittest.main()
