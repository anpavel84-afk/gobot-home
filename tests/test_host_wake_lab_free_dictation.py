"""Free speech monitor: all tests synthetic/fake, NEVER access real microphone."""
import contextlib
import io
import sys
import unittest
from unittest import mock
from services.voice.host_wake_lab.detect import Hypothesis
from services.voice.host_wake_lab.free_dictation import ConsoleTranscripts, live_listen, main


class TranscriptsTests(unittest.TestCase):
    def test_both_partial_updates_and_final_are_visible(self):
        output=[]
        def emit(*items, **_):
            output.append(" ".join(map(str,items)))
        t=ConsoleTranscripts("Vosk",output=emit)
        t.update(Hypothesis("гоби",updated=True),at_s=.32)
        t.update(Hypothesis("гоби",updated=True),at_s=.45)
        t.update(Hypothesis("гоби какая",updated=True),at_s=.62)
        t.update(Hypothesis("гоби какая",endpoint=True),at_s=.93)
        self.assertEqual(len(output),3)
        self.assertIn("partial",output[0])
        self.assertIn("гоби",output[0])
        self.assertIn("гоби какая",output[-1])
        self.assertIn("FINAL",output[-1])

    def test_empty_hypotheses_do_not_pollute_console(self):
        output=[]
        t=ConsoleTranscripts("T-one",output=lambda *a,**_:output.append(a))
        t.update(Hypothesis("",updated=True),at_s=0)
        t.update(Hypothesis("г",updated=False),at_s=.3)
        self.assertEqual(output,[])

    def test_duplicate_model_rejected_without_consent(self):
        stderr=io.StringIO()
        with mock.patch.object(sys,"argv",[
             "dictation","--models-root","not-real",
             "--models","vosk","vosk"]):
            with contextlib.redirect_stderr(stderr):
                with self.assertRaises(SystemExit):
                    main()
        self.assertIn("duplicate model",stderr.getvalue())

    def test_no_flag_never_loads_models_nor_mic(self):
        stdout=io.StringIO()
        with mock.patch.object(sys,"argv",["dictation",
                                          "--models-root","not-real"]):
            with contextlib.redirect_stdout(stdout):
                main()
        self.assertIn("NO_MIC_CONSENT_FLAG",stdout.getvalue())

    def test_denied_consent_never_loads_models_nor_mic(self):
        stdout=io.StringIO()
        with mock.patch.object(sys,"argv",["dictation",
             "--owner-consent-live","--models-root","not-real"]), \
             mock.patch("builtins.input",return_value="yes"):
            with contextlib.redirect_stdout(stdout):
                main()
        self.assertIn("NOT_RUN_CONSENT_DENIED",stdout.getvalue())

    def test_two_models_print_live_recognition_on_fake_raw_pcm(self):
        class FakeAsr:
            model_version = "synthetic-only-in-memory"
            def feed_pcm(self, pcm):
                self.assert_bytes = len(pcm)
                return Hypothesis("гоби какая погода", updated=True)
            def reset(self):
                pass

        class FakeRawInputStream:
            def __init__(self, *, callback, **kwargs):
                self.callback = callback
                self.kwargs = kwargs
            def __enter__(self):
                self.callback(b"\x00\x00" * 960, 960, None, None)
                self.callback(b"\x00\x00" * 960, 960, None, None)
                return self
            def __exit__(self, *_):
                return False

        out=io.StringIO()
        with mock.patch("sounddevice.RawInputStream", FakeRawInputStream), \
             mock.patch("services.voice.host_wake_lab.engines.VoskOnline",
                        side_effect=lambda *a, **k: FakeAsr()) as vosk_ctor, \
             mock.patch("services.voice.host_wake_lab.engines.make_backend",
                        side_effect=lambda *a, **k: FakeAsr()), \
             contextlib.redirect_stdout(out):
            live_listen(models_root="FAKE",
                        minutes=0.002, device=1,
                        engine_names=("vosk", "t-one"))
        vosk_ctor.assert_called_once_with("FAKE",num_threads=1,required_words=())
        value=out.getvalue()
        self.assertIn("Vosk",value)
        self.assertIn("T-one",value)
        self.assertIn("гоби какая погода",value)
        self.assertIn("МИКРОФОН ЗАКРЫТ",value)

    def test_session_is_always_bounded(self):
        for n in ("0","40","-1"):
            with self.subTest(minutes=n):
                with mock.patch.object(sys,"argv",[
                     "dictation","--owner-consent-live","--models-root","x",
                     "--minutes",n]):
                    with contextlib.redirect_stderr(io.StringIO()):
                        with self.assertRaises(SystemExit):
                            main()


if __name__=="__main__":
    unittest.main()
