# GoBot HOST-B · Priority change to «Го́би» (16 Nov 2026)

Issue #6: https://github.com/anpavel84-afk/gobot-home/issues/6

**Gate:** SOURCE_IMPLEMENTED / FREE_TESTED. MODEL_NOT_ACCEPTED. New-name human microphone acceptance = NOT_RUN_CONSENT_REQUIRED; board acceptance = NOT_RUN_HOST_A_ONLY; paid calls = 0. Project remains GoBot.

## Independent candidate policy

One single active candidate per recognizer. Priority: Го́би (gobi, first-syllable stress). Competitor: Гло́би (globi), NOT a synonym. Reserve: А, Го́би (a_gobi), kept separate from optional Эй, Го́би (hey_gobi). Neither previous Гобот nor Габот are aliases. CandidateMatcher requires exact first Cyrillic word sequence, two separated ASR hypothesis updates (>=100 ms), no forced one-word decoder grammars or fuzzy aliases. HOST-A activation_approved remains FALSE.

## Verified on actual PLAN local models

Actual Vosk small Russian 0.22 vocabulary lookup: гоби=245950; глоби=-1 (OOV); а=180003; эй=224198; губы=246873; глобус=242704; гобот=-1; робот=122320. Presence in the dictionary is NOT acoustic acceptance. No model retraining done.

Models / licenses / input: Vosk small-ru-0.22, Apache-2.0, native 16k streaming; Sherpa-ONNX T-one Russian streaming-2025-09-08, Apache-2.0, native 8k, only detector resamples 16k->8k; Sherpa-ONNX small Zipformer Russian 2024-09-18, Apache-2.0, native 16k but OFFLINE rolling-window, not genuine online wake. Runtime Python 3.14.4, vosk 0.3.45, sherpa-onnx 2.0.1, CPU Ryzen 7 7840HS.

## Same PCM synthetic baseline (NOT a human voice result)

One existing Piper ru_RU-denis-medium Russian synthetic voice generated 38 independent 16k PCM clips. Every candidate and engine received THE SAME audio. Each candidate scored 6 positives and 32 negatives; other candidates were counted as negative phrases. Includes standalone names, coarticulated weather and time queries, Гобот, робот, губы, глобус, ambient-like spoken sentences. One synthetic voice does not establish first-syllable stress, actual quiet/far field, TV or music quality.

Catalog SHA256: f347a09dcf1d7a1e9ae3beab94bbc69976ad4c101f7a1a26fcd5a67d6b85995f
Common PCM hashes SHA256: 1c9a0ee460cde609e621475976339ace2a5d27e76f85079f977ca22061646b27
Detailed per-clip JSON on PLAN only: C:\Users\PLAN\gobot\HOST-B-lab\results\gobi-independent-v1.json.
PCM fixtures and model weights are NOT committed/uploaded.

| Engine | Independent phrase | TP / 6 | False events / 32 | Cold start ms | CPU seconds | RTF | Peak process RAM MB |
|---|---|---:|---:|---:|---:|---:|---:|
| T-one | Гоби | 0/6 | 2/32 | 2272 | 10.45 | .183 | 363.1 |
| Vosk | Гоби | 0/6 | 0/32 | 1022 | 31.83 | .558 | 274.2 |
| Zipformer window | Гоби | 0/6 | 0/32 | 2212 | 8.33 | .146 | 158.8 |
| T-one | Глоби | 0/6 | 0/32 | 2099 | 10.69 | .188 | 386.5 |
| Vosk | Глоби | BLOCKED_OOV | — | — | — | — | — |
| Zipformer window | Глоби | 0/6 | 0/32 | 2064 | 8.06 | .141 | 160.4 |
| T-one | А, Гоби | 0/6 | 0/32 | 2007 | 10.08 | .176 | 388.8 |
| Vosk | А, Гоби | 0/6 | 0/32 | 741 | 32.20 | .565 | 276.4 |
| Zipformer window | А, Гоби | 0/6 | 0/32 | 1959 | 8.03 | .141 | 161.7 |
| T-one | Эй, Гоби | 0/6 | 0/32 | 1950 | 9.22 | .162 | 389.7 |
| Vosk | Эй, Гоби | 0/6 | 0/32 | 711 | 32.03 | .560 | 279.9 |
| Zipformer window | Эй, Гоби | 0/6 | 0/32 | 1918 | 8.02 | .140 | 162.1 |

RTF = offline batch inference wall duration / processed speech duration; it is NOT name-end detection latency. CPU seconds and peak RAM are real measurements, the latter for the whole Python process. In every combination name-end-to-confirmation/ACK P50/P95 is NOT_MEASURED: no independently annotated actual speech end and no correct synthetic hits. False-wakes/hour is NOT_MEASURED: 32 short synthetic negative clips are NOT 30 minutes of real negative background. No candidate is ACCEPTED.

T-one's **two false events for a standalone Gobi-only detector** came from the synthetic prefixed phrases a_gobi_02 and a_gobi_05. Its ASR apparently omitted the initial «А» in both, demonstrating why the two candidate names must be evaluated separately. Diagnostic unforced ASR of synthetic «Гоби какая сегодня погода» returned «какая сегодня погода» (T-one), «бобби какая сегодня» (Vosk), and a «бобби ...» partial (Zipformer). Those are observed synthetic transcription examples only; they do not prove what a person speaking distinctly stressed «Го́би» will produce.

## Real human PC microphone tests are prepared, NOT launched by assistant

PLAN audio input device 21 passed a non-capturing 16k mono PortAudio settings check. Four bounded consent-gated launchers have been created ON PLAN outside Git:

- C:\Users\PLAN\gobot\HOST-B-lab\START_GOBI_MIC_TEST.cmd (Vosk LIVE + T-one SHADOW replay)
- C:\Users\PLAN\gobot\HOST-B-lab\START_GLOBI_MIC_TEST.cmd (T-one LIVE + Zipformer SHADOW replay)
- C:\Users\PLAN\gobot\HOST-B-lab\RESERVE_A_GOBI_MIC_TEST.cmd
- C:\Users\PLAN\gobot\HOST-B-lab\RESERVE_HEY_GOBI_MIC_TEST.cmd

Each runs only one candidate, with six natural positive prompts (isolated, no-pause weather/time, quiet and ~2m) and nine independent negative prompts. Optional 30s real TV plus 30s real music test. Owner physically at PLAN must enter exact YES-PC-MIC locally before microphone opens; then press Enter to start each prompt and confirm with y, yes or да after speaking. The first decoder handles live streaming PCM, while the second decodes the same temporary RAM buffer AFTER mic closes (its delay is not live latency). PCM is zeroized after use. Only numeric level, counts, timestamps, ID and CPU/RAM metadata are saved, not speech or transcripts. A local Windows beep is requested on candidate detection; its API call is NOT acoustic onset confirmation.

For a meaningful false-events/hour estimate, a separate finite 30-minute real-negative background test is available but NOT RUN:

C:\Users\PLAN\gobot\HOST-B-lab\OPTIONAL_GOBI_BACKGROUND_30MIN.cmd

This tool also needs new local typed YES-PC-MIC and final YES-NEGATIVE confirmation, monitors one candidate/engine, stores NO raw voice, keeps only event counts/timestamps and actual captured duration. It computes false wakes/hour ONLY after >=1800 seconds of confirmed address-free TV/music/conversation. It never creates an always-on microphone service. Zero observed false events over 30 minutes is NOT proof of zero underlying risk. Avoid running concurrently with HOST-A latency/hardware tests.

## Ready Russian KWS availability

Sherpa-ONNX does implement open-vocabulary keyword spotting with on-the-fly keyword definition, but its verified published KWS acoustic checkpoints are Chinese/English (Zipformer zh-en, WenetSpeech Chinese, GigaSpeech English). No production-ready Russian KWS acoustic model for Гоби was verified from that official list. Do NOT pretend an English model directly supports the requested Russian utterance without validation, or train a custom model without Owner permission.

Official docs: https://k2-fsa.github.io/sherpa/onnx/kws/index.html ; https://k2-fsa.github.io/sherpa/onnx/kws/pretrained_models/index.html ; https://alphacephei.com/vosk/models .

## Contract, source and reproduction

All changes remain only under services/voice/host_wake_lab/ and tests/test_host_wake_lab_*. HOST-A owns the canonical AudioChunk(PCM16/epoch/first sample/received_monotonic_ns) -> WakeEvent(end_sample_index/phrase_id/detector_id/detected_monotonic_ns) dataclasses and gateway activation logic. The same B bridge accepts a single candidate_id and defaults to activation_approved=False. NO firmware flash, Opus/gateway/Brain edits, system changes, training, cloud audio/paid calls, or auto-merge.

Re-run from Windows PowerShell on PLAN:

~~~powershell
Set-Location 'C:\Users\PLAN\gobot\GoBotHome-wake-lab'
$py='C:\Users\PLAN\gobot\HOST-B-lab\.venv\Scripts\python.exe'
$lab='C:\Users\PLAN\gobot\HOST-B-lab'
& $py -m unittest discover -s tests -p 'test_host_wake_lab_*.py' -v
& $py -m services.voice.host_wake_lab.gobi_benchmark --fixtures-dir "$lab\fixtures\gobi_v1" --models-root "$lab\models" --out "$lab\results\gobi-retest.json" --candidates gobi globi a_gobi hey_gobi --engines t-one vosk zipformer-window --threads 1
~~~

Next decision gate: real human voice success AND low false activations with near words, TV/music/background; annotated p50/p95 only with reliable actual name-end marks. All synthetic positives passing is itself insufficient for acceptance.
