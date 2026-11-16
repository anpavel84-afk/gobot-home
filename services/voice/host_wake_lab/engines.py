"""Ready-made recognizers only. No private training, cloud audio, or providers.

T-one is a native 8-kHz online recognizer. Its 16-kHz input is filtered
and downsampled exclusively inside this module.
Zipformer RU is truly OFFLINE: the rolling-window adapter is a benchmark
experiment and must never be mislabeled as native streaming.
Vosk is fail-closed if the required Russian names are OOV.
"""
from __future__ import annotations
from collections import deque
import json
from pathlib import Path

from .detect import Hypothesis


class VocabularyUnavailable(RuntimeError):
    pass


class ModelUnavailable(RuntimeError):
    pass


class Decimate2:
    """Stateful anti-aliased 16 kHz to 8 kHz, preserve global sample parity."""
    def __init__(self):
        import numpy as np
        idx = np.arange(63, dtype=np.float64) - 31
        cutoff = 0.225
        h = 2 * cutoff * np.sinc(2 * cutoff * idx) * np.hamming(63)
        self.taps = (h / h.sum()).astype(np.float32)
        self.prev = np.zeros(62, dtype=np.float32)
        self.samples_in = 0

    def feed(self, pcm):
        import numpy as np
        x = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.
        concat = np.concatenate((self.prev, x))
        y = np.convolve(concat, self.taps, mode="valid")
        self.prev = concat[-62:].copy()
        offset = self.samples_in % 2
        self.samples_in += len(x)
        return y[offset::2].astype(np.float32, copy=False)


def _required(path: Path):
    if not path.is_file():
        raise ModelUnavailable("model_file_missing:" + str(path))
    return str(path)


class ToneOnline:
    detector_id = "sherpa-onnx-t-one-2025-09-08"
    model_version = "sherpa-onnx-streaming-t-one-russian-2025-09-08"
    license = "Apache-2.0 (bundled LICENSE and upstream T-one)"
    native_rate = 8000
    streaming = True

    def __init__(self, models_root, num_threads=2):
        import sherpa_onnx
        base = Path(models_root) / self.model_version
        self.recognizer = sherpa_onnx.OnlineRecognizer.from_t_one_ctc(
            tokens=_required(base / "tokens.txt"),
            model=_required(base / "model.onnx"),
            sample_rate=8000, num_threads=num_threads,
            enable_endpoint_detection=True,
            rule2_min_trailing_silence=1.0,
            provider="cpu",
            debug=False,
        )
        self.reset()

    def reset(self):
        self.stream = self.recognizer.create_stream()
        self.resampler = Decimate2()
        self.last_text = ""

    def feed_pcm(self, pcm_s16le):
        arr = self.resampler.feed(pcm_s16le)
        self.stream.accept_waveform(8000, arr)
        updated = False
        while self.recognizer.is_ready(self.stream):
            self.recognizer.decode_stream(self.stream)
            updated = True
        if updated:
            result = self.recognizer.get_result_all(self.stream)
            self.last_text = str(result.text)
        endpoint = self.recognizer.is_endpoint(self.stream)
        out = Hypothesis(text=self.last_text, endpoint=bool(endpoint), updated=updated)
        if endpoint:
            self.recognizer.reset(self.stream)
            self.last_text = ""
        return out


class VoskOnline:
    detector_id = "vosk-small-ru-0.22"
    model_version = "vosk-model-small-ru-0.22"
    license = "Apache-2.0 (alphacephei.com/vosk/models)"
    native_rate = 16000
    streaming = True

    def __init__(self, models_root, num_threads=2, required_words=("гобот", "габот")):
        from vosk import Model, KaldiRecognizer, SetLogLevel
        self._kaldi_recognizer = KaldiRecognizer
        base = Path(models_root) / self.model_version
        if not base.is_dir():
            raise ModelUnavailable("model_directory_missing:" + str(base))
        SetLogLevel(-1)
        self.model = Model(str(base))
        if not hasattr(self.model, "vosk_model_find_word"):
            raise VocabularyUnavailable("no_verified_vocab_lookup")
        self.word_ids = {w: self.model.vosk_model_find_word(w)
                         for w in required_words}
        missing = [word for word, idx in self.word_ids.items() if idx < 0]
        if missing:
            raise VocabularyUnavailable("OOV_no_untrained_repair:" + ",".join(missing))
        self.reset()

    def reset(self):
        self.rec = self._kaldi_recognizer(self.model, 16000)
        self.rec.SetWords(True)
        self.rec.SetPartialWords(True)

    def feed_pcm(self, pcm_s16le):
        endpoint = self.rec.AcceptWaveform(pcm_s16le)
        payload = json.loads(self.rec.Result() if endpoint else self.rec.PartialResult())
        return Hypothesis(text=payload.get("text" if endpoint else "partial", ""),
                          endpoint=bool(endpoint), updated=True)


class ZipformerWindow:
    detector_id = "sherpa-onnx-small-zipformer-ru-2024-09-18-window"
    model_version = "sherpa-onnx-small-zipformer-ru-2024-09-18"
    license = "Apache-2.0 (derived from Vosk small RU)"
    native_rate = 16000
    streaming = False

    def __init__(self, models_root, num_threads=2):
        import sherpa_onnx
        base = Path(models_root) / self.model_version
        self.recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
            encoder=_required(base / "encoder.int8.onnx"),
            decoder=_required(base / "decoder.onnx"),
            joiner=_required(base / "joiner.int8.onnx"),
            tokens=_required(base / "tokens.txt"),
            num_threads=num_threads, sample_rate=16000, provider="cpu",
            decoding_method="greedy_search",
        )
        self.reset()

    def reset(self):
        self.frames = deque()
        self.size = 0
        self.since_decoding = 0
        self.last_text = ""

    def feed_pcm(self, pcm_s16le):
        import numpy as np
        self.frames.append(pcm_s16le)
        self.size += len(pcm_s16le) // 2
        self.since_decoding += len(pcm_s16le) // 2
        max_size = 2 * 16000
        while self.size > max_size and len(self.frames) > 1:
            dropped = self.frames.popleft()
            self.size -= len(dropped) // 2
        if self.size < 16000 or self.since_decoding < 4800:
            return Hypothesis(self.last_text, updated=False)
        self.since_decoding = 0
        pcm = b"".join(self.frames)
        samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.
        stream = self.recognizer.create_stream()
        stream.accept_waveform(16000, samples)
        self.recognizer.decode_stream(stream)
        result = (self.recognizer.get_result(stream)
                  if hasattr(self.recognizer, "get_result") else stream.result)
        self.last_text = str(result.text if hasattr(result, "text") else result)
        return Hypothesis(self.last_text, updated=True)


REGISTRY = {"t-one": ToneOnline, "vosk": VoskOnline, "zipformer-window": ZipformerWindow}


def make_backend(name: str, models_root: str | Path, threads: int = 2):
    if name not in REGISTRY:
        raise ValueError("unknown_backend:" + name)
    return REGISTRY[name](models_root, num_threads=threads)
