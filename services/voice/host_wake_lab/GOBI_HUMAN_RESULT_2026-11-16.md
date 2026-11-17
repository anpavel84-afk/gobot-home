# HOST-B: real human microphone result — Го́би — 16 November 2026

Issue: https://github.com/anpavel84-afk/gobot-home/issues/6

**Status: HUMAN_TESTED_NOT_ACCEPTED.** An Owner-present, per-run-consented test on the Windows PLAN PC finished at 20:04 -03 on 2026-11-16. Local-only metadata source (not committed): C:\Users\PLAN\gobot\HOST-B-lab\results\gobi-human-gobi-20261116T230421Z.json.

The first test attempt failed before producing a report; the repaired run used Windows MME Microphone Array #1, mono PCM signed 16-bit 16000 Hz rather than the earlier WDM-KS device #21. The real input was non-silent and no capture error occurred. Nine trials were explicitly owner-confirmed; none excluded.

| Recognizer / evaluation | Human positive detections | Misses | Near-negative phrases | Real background | False events | p50/p95 name-end latency |
|---|---:|---:|---:|---:|---:|---|
| Vosk small Russian 0.22 **LIVE** | 0/3 | 3 | 0/4 false | 0/36 s false | 0 | NOT_MEASURED |
| Sherpa-ONNX T-one Russian **SAME HUMAN PCM SHADOW REPLAY** | 0/3 | 3 | 0/4 false | 0/36 s false | 0 | NOT_MEASURED |

Three positive trials, all six seconds and owner-confirmed: isolated Го́би (mic RMS -36.2, peak -9.2 dBFS); continuous Го́би, какая сегодня погода? (RMS -34.2, peak -8.2 dBFS); continuous Го́би, сколько времени? (RMS -33.5, peak -8.7 dBFS). No wake events in either engine.

Four separate six-second near-negative trials were robot, gobot, lips (губы), and globe (глобус). The 36 seconds of true non-address background were 6 seconds of unrelated room conversation plus 30 seconds of actual TV. All confirmed 0 events. **False wakes/hour is NOT_MEASURED**, not zero per hour, because independent background exposure is under 1800 seconds. 36 seconds from Vosk and T-one is the same shared audio, not 72 separate seconds.

Process measured wall 243.87 seconds including human prompts; CPU 46.266 seconds; peak total process RAM 803.3 MiB. Three models were resident for the additional console trace and this value is NOT the RAM footprint of a single production decoder. Vosk cold load 1247.2 ms; T-one load 2049.5 ms. Capture queue peak 182.14 ms on one unrelated negative trial. Cold-start/queue-delay values are NOT wake latency.

Actual human partial/final hypotheses were printed locally to the PLAN console but were deliberately **not persisted**. They are no longer available after the console exited. Therefore the real spoken word replacement (if any) remains UNKNOWN. Synthetic diagnostic evidence from a DIFFERENT Piper recording found Vosk output бобби, T-one omitted the name, Zipformer output боби/бобби; it would be false to assert this happened in human speech. The Piper phonemizer mapped Гоби to IPA ɡˈobʲɪ (first-syllable stress); PCM format was validated. No raw PCM, family audio, transcripts, or personal voice files were saved or uploaded.

Next most informative test: user locally repeats a short consented Го́би / Эй, Го́би utterance and reports the visible LIVE_ASR / ASR_TRACE hypothesis text; retain only count summaries in GitHub. Confirm whether the ASR substitutes a word or the two-stable-update matcher loses a correctly recognized prefix. Human reserve Эй, Го́би and separate competitor Гло́би have NOT been tested. A, Гоби is NOT an active target and old archived measurements remain untouched.

**Release gates:** activation_approved=false; HOST-A retains sole integration ownership under existing AudioChunk -> WakeEvent contract; no Spotpear firmware, gateway, Brain, paid B/C/CLI sessions, provider audio transmission or standing capture service touched. PR #9 remains draft/DO NOT MERGE.
