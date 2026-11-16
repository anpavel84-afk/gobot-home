"""GoBot HOST-B: owner's free-form, finite PC microphone ASR console.

No wake word filtering: say ANY word repeatedly and see actual hypotheses from
two existing Russian engines. It is an interactive choice aid, NOT a validated
wake detector or activation test.

PRIVACY:
 - microphone can open ONLY after human types YES-PC-MIC on PLAN itself;
 - raw PCM stays in a bounded in-RAM queue, never written or transmitted;
 - ASR transcripts are printed ONLY in local Windows console, not persisted;
 - no subprocess, log file, cloud, gateway, Brain, or paid API calls;
 - no auto-retry microphone capture; ends on Ctrl+C / elapsed timeout.

Input 16 kHz mono signed int16; Vosk native 16k; T-one streaming 8k after the
existing B-owned stateful resampler. Uses the safe MME device 1 by default.
"""
from __future__ import annotations

import argparse
import json
import math
import queue
import sys
import time

PCM_HZ = 16000
FRAME_SAMPLES = 960
FRAME_BYTES = FRAME_SAMPLES * 2
MAX_MINUTES = 30
INPUT_CONSENT = "YES-PC-MIC"


class ConsoleTranscripts:
    """Only output a changing hypothesis, without keeping personal transcripts.

    Model text stays in RAM for as long as needed to compare adjacent updates.
    No logger and no JSON transcript/report output.
    """
    def __init__(self, name: str, output=print):
        self.name = name
        self.output = output
        self.last_text = ""

    def update(self, hyp, *, at_s: float) -> None:
        if not hyp.updated and not hyp.endpoint:
            return
        current = str(hyp.text).strip()
        if hyp.endpoint:
            # Real decoder endpoint, not an inferred acceptance.
            if current:
                self.output(f"[{at_s:7.2f}s] {self.name:6s} FINAL   │ {current}", flush=True)
            elif self.last_text:
                self.output(f"[{at_s:7.2f}s] {self.name:6s} END     │ (end of segment; no new final)", flush=True)
            self.last_text = ""
        elif current and current != self.last_text:
            self.output(f"[{at_s:7.2f}s] {self.name:6s} partial │ {current}", flush=True)
            self.last_text = current

    def final_only(self, value: str, *, at_s: float) -> None:
        value = str(value).strip()
        if value:
            self.output(f"[{at_s:7.2f}s] {self.name:6s} STOP    │ {value}", flush=True)


def _finish_backend(name, backend) -> str:
    """Decoder-produced unfinished partial at end of session; not wake latency."""
    try:
        if name == "Vosk":
            return json.loads(backend.rec.FinalResult()).get("text", "")
        if name == "T-one":
            backend.stream.input_finished()
            while backend.recognizer.is_ready(backend.stream):
                backend.recognizer.decode_stream(backend.stream)
            return str(backend.recognizer.get_result_all(backend.stream).text)
    except Exception:
        return ""
    return ""


def live_listen(*, models_root, device: int = 1, minutes: float = 15.0,
                engine_names=("vosk", "t-one"), output=print):
    """Finite open mic; callable only from main AFTER local typed owner consent.

    Never save PCM or text. Input callback holds <=32 60ms frames (~1.92s).
    Fail closed on drops/overflows; no hidden resume or permanent listeners.
    """
    import sounddevice as sd
    import numpy as np
    from .engines import VoskOnline, make_backend

    backends = []
    print("Загружаю локальные модели (без облака)...", flush=True)
    for name in engine_names:
        if name == "vosk":
            # Free dictation must NOT require previous GoBot/Gabot wake words.
            # Keep strict Vosk OOV blocking in existing wake detectors intact.
            backend = VoskOnline(models_root, num_threads=1, required_words=())
        else:
            backend = make_backend(name, models_root, threads=1)
        backends.append((name, backend))
        print(f"Модель {name} готова: {backend.model_version}", flush=True)

    q = queue.Queue(maxsize=32)
    audio_errors = []
    frames_processed = 0
    last_level_output_s = 0.0
    observed_peak = 0
    trace = [(name, ConsoleTranscripts("Vosk" if name == "vosk" else "T-one",
                                      output=output))
             for name,_ in backends]
    statuses = []
    def callback(indata, frame_count, timestamp, status):
        if status:
            audio_errors.append("portaudio_input_status")
            return
        if frame_count != FRAME_SAMPLES:
            audio_errors.append("unexpected_frame_size")
            return
        try:
            q.put_nowait((bytes(indata), time.monotonic_ns()))
        except queue.Full:
            audio_errors.append("input_queue_overflow")

    print()
    print("="*70,flush=True)
    print("  ● МИКРОФОН: будет открыт на Windows PLAN",flush=True)
    print("  Говори ЛЮБЫЕ имена и слова; делай паузу 1–2 сек между повторами.",flush=True)
    print("  Vosk и T-one слушают ОДИН И ТОТ ЖЕ поток одновременно.",flush=True)
    print("  partial = промежуточный текст; FINAL = конец фразы у модели.",flush=True)
    print("  Несовпадение текста показывает саму ошибку ASR, а не wake-механизма.",flush=True)
    print("  Ни одна фраза, запись или расшифровка не сохраняется на диск.",flush=True)
    print("  Ctrl+C = закончить. Время ограничено; скрытого фонового сервиса нет.",flush=True)
    print("="*70,flush=True)
    started=time.monotonic()
    try:
        with sd.RawInputStream(
                samplerate=PCM_HZ,
                blocksize=FRAME_SAMPLES,
                channels=1,
                dtype="int16",
                device=device,
                callback=callback):
            print("● СЛУШАЮ. Начинай говорить.", flush=True)
            while time.monotonic() - started < minutes * 60:
                if audio_errors:
                    raise RuntimeError("audio_stream_interrupted:" + audio_errors[0])
                try:
                    block, recv_ns = q.get(timeout=0.25)
                except queue.Empty:
                    continue
                if len(block) != FRAME_BYTES:
                    raise RuntimeError("invalid_pcm_size")
                at_s = (time.monotonic() - started)
                # Numeric-only mic level diagnostic. No speech or audio stored.
                samples = np.frombuffer(block, dtype="<i2")
                if len(samples):
                    observed_peak = max(observed_peak, int(np.max(np.abs(
                        samples.astype(np.int32)))))
                if at_s - last_level_output_s >= 5.0:
                    peak_db = 20 * math.log10(max(observed_peak, 1e-8) / 32768)
                    output(f"[{at_s:7.2f}s] MIC    LEVEL   │ пик {peak_db:.1f} dBFS (только уровень)", flush=True)
                    last_level_output_s = at_s
                    observed_peak = 0
                for (name, backend), (_, tracer) in zip(backends, trace):
                    hyp = backend.feed_pcm(block)
                    tracer.update(hyp, at_s=at_s)
                frames_processed += 1
    except KeyboardInterrupt:
        print("\n■ Завершено пользователем (Ctrl+C).",flush=True)
    except Exception as exc:
        # No transcript in the error report.
        print(f"\n! AUDIO ERROR {type(exc).__name__}: {str(exc)[:220]}",flush=True)
        print("Проверь микрофон Windows. Программа не перезапускает запись сама.",flush=True)
    finally:
        # Ensure mic device is CLOSED before any final decoder operations.
        print("\n■ МИКРОФОН ЗАКРЫТ.",flush=True)
        at_s=time.monotonic() - started
        for (name, backend), (_, tracer) in zip(backends, trace):
            result=_finish_backend("Vosk" if name=="vosk" else "T-one",backend)
            tracer.final_only(result,at_s=at_s)
            backend.reset()
        # Explicitly drop queued buffers; no file or transcript persistence.
        while not q.empty():
            q.get_nowait()
        print(f"PCM-пакетов обработано: {frames_processed}, звук/текст не сохранены.",
              flush=True)
        print("Никаких wake-активаций, никаких платных API.",flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--owner-consent-live", action="store_true")
    p.add_argument("--models-root", required=True)
    p.add_argument("--device", type=int, default=1)
    p.add_argument("--minutes", type=float, default=15.0)
    p.add_argument("--models", nargs="+", choices=("vosk", "t-one"),
                   default=["vosk", "t-one"])
    a = p.parse_args()
    if not 1 <= a.minutes <= MAX_MINUTES:
        p.error("duration must be 1..30 minutes; no unlimited background mic")
    if len(set(a.models)) != len(a.models):
        p.error("duplicate model not allowed")
    if not a.owner_consent_live:
        print("NO_MIC_CONSENT_FLAG; no microphone opened.")
        return
    print("Свободное распознавание, а НЕ запланированный тест wake word.")
    print("Микрофон PLAN MME #1; нет записи аудио или расшифровок.")
    print("Введите YES-PC-MIC для разрешения ОДНОЙ ограниченной сессии.")
    if input("Local Owner consent: ").strip() != INPUT_CONSENT:
        print("NOT_RUN_CONSENT_DENIED; no microphone opened.")
        return
    live_listen(models_root=a.models_root, device=a.device,
                minutes=a.minutes, engine_names=tuple(a.models))


if __name__ == "__main__":
    main()
