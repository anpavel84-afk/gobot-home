# HOST-B / Monika: first human speech trial and corrected scoring

Date: 2026-11-16 22:35 (-03). Owner-selected word: Моника.

**Measured human voice on PLAN (MME microphone #1):**
- Vosk small-ru-0.22 **LIVE**: 2 correct Monika wake events / 3 Owner-confirmed utterances; 1 miss (standalone name).
- Sherpa-ONNX T-one Russian 2025-09-08 **SHADOW replay of exactly the same human PCM**: 3 correct Monika wake events / 3 confirmed utterances; 0 misses. A secondary model executed after the microphone closed, so this DOES NOT measure its live detection latency.
- Correctly detected utterances for Vosk: Monika + weather without pause; Monika + time without pause. Standalone Monika missed in LIVE Vosk but detected by T-one shadow.
- Each recognizer emitted 0 false wake events over 6 confirmed negative trials: monitor, monik, Monya, a conversational mention of Monika, unrelated conversation, and actual TV.
- Genuine negative background: 6s conversational mention + 6s unrelated conversation + 30s TV = **42 seconds**, shared between both recognizers. **False wakes per hour is NOT_MEASURED** (less than 1800s). Four remaining short negative phrases are counted as discrete near-negative trials, not hours of background.
- Mic signals in the three positives were non-silent, peaks -23.9, -22.1 and -24.6 dBFS. There were 0 capture errors and 0 excluded trials.
- Process CPU = 48.906s across 254.7s interactive wall time; peak process RAM = 798.1 MiB (including THREE resident model objects for console diagnostics, NOT a single-model requirement). Vosk load = 881.9ms; T-one load = 2130.8ms; these are NOT wake latencies.
- There were 2 local cue API requests on Vosk candidates, with 0.01ms and 149.65ms request delay after event timestamps; **audible start and true name-end latency P50/P95 NOT_MEASURED**. No actual assistant conversation was opened on the PC.

## Source and correction provenance

The preserved local-only original report:
C:\Users\PLAN\gobot\HOST-B-lab\results\gobi-human-monika-20261117T013510Z.json

The new local-only, metadata-only corrected report:
C:\Users\PLAN\gobot\HOST-B-lab\results\monika-corrected-20261117T013510Z.json

Bug: the positive trial catalog passed user-facing Cyrillic display name "Моника" to score_trial(), but emitted event phrase_id was "monika". This misclassified real observed events as misses. The original report's per-trial **primary_event_count** of 1 for weather/time and **shadow_event_count** of 1 for all three positives, plus 2 actual Vosk cue API event records with phrase_id monika, establish these corrected numbers. Each isolated trial had exactly one active CandidateMatcher("monika"), so the shadow events can only have phrase_id monika. Counts are auditable from original JSON. Original report was NOT modified, personal audio or transcript was not saved, and NO additional model inference or synthetic correction was invented.

Fixed future trial catalog to use *machine candidate ID* for expected_phrase and human-facing label only for prompt. Regression tests verify that every currently active candidate has matching internal phrase IDs and catches the prior bug. Original vs corrected raw JSON remains outside Git.

## Real physical Spotpear separate from PLAN PC trial

HOST-A has independently installed firmware 0.4.13-dev-host-a-rc1-r3 and launched its own free, finite Monika hardware pilot using the existing separate TLS test listener and COM3. At the read-only observation captured on 16 Nov at approximately 22:36 -03, HOST-A status showed a connected Spotpear, 4795 authenticated device Opus packets (287.6 seconds), 0 device-initiated wake activations, 0 local replies, paid calls 0; the physical pilot **was still running**. Device microphone acoustic quality is NOT inferred from PC microphone success. A currently owns the hardware; B did not restart, duplicate, or modify A's pilot or production gateway.

Hardware pilot activation remains experimental; it does not imply acceptance for persistent home monitoring. Need **physical Owner speech into the device**, sufficient human positive and negative testing, TV/background false wake monitoring, and audible meaningful response from the actual Spotpear. HOST-A alone can own the guarded physical trial. Do NOT enable production hardware gateway or paid B/C/CLI sessions based on 3 positive PC samples.

## Decision and release gates

- SOURCE_IMPLEMENTED / HUMAN_PC_WAKE_EVENTS_DETECTED: YES for Monika, with counts above.
- MODEL_ACCEPTED_FOR_ALWAYS_ON_HOME: NO (three positives and 42 seconds background are insufficient).
- HUMAN_SPOTPEAR_WAKE_ACCEPTED: NOT_MEASURED (0 observed physical wakes as of snapshot).
- FREE_HARDWARE_E2E / meaningful speech confirmed by Owner: NOT_YET_HUMAN_CONFIRMED.
- P50/P95 from acoustic name end: NOT_MEASURED.
- False wakes/hour from >=30min *real household* background: NOT_MEASURED.
- Paid calls / recorded raw audio / recorded transcripts: ZERO. GoBot project name unchanged.

Issue #6 remains OPEN. Source in B-only draft PR #9; do not merge automatically.
