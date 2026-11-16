# GoBot HOST-B — Russian Wake Recognition Lab (#6)

**CURRENT OWNER SELECTION: «Моника»**. Vosk Russian vocabulary ID 57908 verified on PLAN. New B-only exact-name matcher, consented live PC mic launcher and default-shadow HOST-A adapter have been implemented. Physical Spotpear RC1 already flashed by HOST-A, but production wake remains OFF and requires an approved A-owned finite pilot. See [MONIKA_STATUS_2026-11-16.md](MONIKA_STATUS_2026-11-16.md). Previous «Гоби/Глоби/Эй, Гоби» experiments below are ARCHIVED historical comparisons and not the new active wake target.

**OWNER PRIORITY (2026-11-16): «Го́би» first-syllable stress; «Эй, Го́би» reserve; «Гло́би» separate competitor.** «А, Гоби» is excluded from active targets/aliases (historical synthetic results only). Legacy «Гобот/Габот» results are historical. Synthetic benchmark/vocabulary details: [GOBI_REPORT_2026-11-16.md](GOBI_REPORT_2026-11-16.md); actual Owner human mic outcome: [GOBI_HUMAN_RESULT_2026-11-16.md](GOBI_HUMAN_RESULT_2026-11-16.md). GoBot project name unchanged and no wake enabled on the physical speaker.

**Current gate: SOURCE_IMPLEMENTED / FREE_TESTED / HUMAN_TESTED_NOT_ACCEPTED.**
PLAN human mic «Го́би» self-confirmed Vosk **0/3** and T-one same-human-PCM shadow **0/3**, with 0 false wake events on six short negative trials (36 seconds real non-address background). Real false wakes/hour and acoustic name-end P50/P95 are **NOT_MEASURED**. BOARD_HUMAN_ACCEPTED=NOT_RUN_HOST_A_ONLY; PAID_CALLS=0.

This is an isolated host-only research implementation, not a production wake module. It does not modify the HOST-A gateway, Opus path, firmware, active Brain, running workers, system Python, or the canonical PCM/WakeEvent contract. Its separate PLAN worktree is feat/host-wake-lab-public, rebased for safe publication on sanitized public HOST snapshot f24c32d5, whose tree exactly equals local 64ba27e2 (H0 descendant bf8a2e98). No private PLAN ancestry is part of the published branch; never reset to stale a31674e.

## Owner's open-microphone free-form word finder (NEW)

Free dictation Vosk is intentionally created with required_words=() so the historical wake vocabulary (гобот/габот) CANNOT prevent an open-vocabulary model load. This is a **local free-dictation-only override**, not a relaxation of the strict existing wake mode. Verified loading BOTH real installed models (Vosk + T-one) on PLAN without opening the mic; separate no-mic regression confirms the free constructor uses no required wake words.

Use the local Windows PLAN launcher (not committed): C:\Users\PLAN\gobot\HOST-B-lab\START_FREE_DICTATION.cmd . An equivalent clean launcher is C:\Users\PLAN\gobot\HOST-B-lab\FREE_SPEECH_MIC_CONSOLE.cmd . Both invoke free_dictation.py from the isolated B worktree and use the existing **Vosk 16k + T-one 8k streaming engines** on the SAME Windows MME #1 mono16k microphone signal. This is an **unrestricted ASR transcription console**, NOT a wake detector; it accepts any spoken names without a whitelist, shows actual changing **partial** and native **final** hypotheses separately for Vosk and T-one, and prints a numerical audio level every five seconds. No metric or candidate is silently marked as accepted. The Owner can listen for 1–2 second pauses between repeated variants and subjectively select promising words for later blinded false-wake tests.

Start requires user physically at PLAN to type exact YES-PC-MIC each time. Runs at most **15 minutes** by launcher (module hard maximum 30 minutes), also stops with Ctrl+C. No audio file, transcript, stderr log, background service, cloud transfer, gateway/Brain state, paid API, or ASR models download. PCM lives in a <=32-frame transient queue and is discarded; a mutable LAST interim text string exists only in RAM for console de-duplication. Model/source code and repeatable unit tests are public, but local household speech remains **not recorded**. If another monitor is active, do not start another session; one local owner console only.

## API and safety

- detect.py: WakeLab.feed(pcm_s16le, stream_epoch, sample_index, received_monotonic_ns, speaking=False) consumes mono s16le PCM16 at 16 kHz and returns laboratory candidate dictionaries with the exact A-owned WakeEvent fields (stream_epoch, end_sample_index, phrase_id, detector_id, detected_monotonic_ns, confidence or null).
- bridge.py: HostWakeDetectorAdapter implements HOST-A's exact v1 protocol: feed_chunk(AudioChunk)->WakeEvent|None and reset(). It consumes the A-owned received_monotonic_ns and returns the A-owned WakeEvent class, never a duplicate contract class. The adapter returns None in shadow mode by default, even when ASR finds a candidate. Only HOST-A can deliberately activate after acceptance. Integration was tested using actual published A AudioChunk, WakeEvent, and HostCore classes with a **fake** speech hypothesis: event constructed, HostCore accepted 1 activation, no physical device, no paid call.
- engines.py: native streaming T-one 8 kHz with private 16→8 FIR; small Vosk 16 kHz fails closed on OOV, Zipformer RU is **offline rolling-window**, not native streaming.
- Strict HOST-A v1 bounds: 1–960 PCM samples per chunk, ASCII-safe epoch token, sample_index continuity and monotonic nanoseconds. Two spaced ASR updates before event, one event per segment, no forced one-word grammar/fuzzy aliases. An event's end_sample_index is the **confirmation-frame end**, NOT independently annotated acoustic end of the wake word; latency from real name end still requires separate human annotation.
- live.py: no mic until Owner locally types YES-PC-MIC after an explicit CLI flag and warning. Bounded run; no PCM/transcript writes; no network. One local PC speaker earcon and optional time/timer via deterministic local_command.py + pre-existing read-only Piper Russian TTS. ACK records only API request/return timings, **not verified acoustic playback onset**.
- harness.py: exact 16 kHz mono16 WAV and hashes, same 960-sample frames and 1.2-second silence tail. Never counts synthetic speech as human. P50/P95 require >=20 annotated non-synthetic trials; false wakes/hour requires >=1800 seconds measured nonsynthetic background.
- synthetic.py: Piper synthetic same-utterance name + question, not stitched name-only segments and not proof of human acceptance.

## Installed models and dependencies, isolated outside Git

Models: C:\Users\PLAN\gobot\HOST-B-lab\models
Environment: C:\Users\PLAN\gobot\HOST-B-lab\.venv
Fixtures: C:\Users\PLAN\gobot\HOST-B-lab\fixtures
Reports: C:\Users\PLAN\gobot\HOST-B-lab\results

| Engine | Model version | License | Rate, mode |
|---|---|---|---|
| T-one | sherpa-onnx-streaming-t-one-russian-2025-09-08 | Apache-2.0, bundled LICENSE verified | 8k, true streaming CTC |
| Vosk | vosk-model-small-ru-0.22 | Apache-2.0 in official Vosk list | 16k, online OOV blocked |
| Small Zipformer | sherpa-onnx-small-zipformer-ru-2024-09-18 | Apache-2.0, originating alphacep Hugging Face model card | 16k, offline transducer windows |

Runtimes: Python 3.14.4 isolated; sherpa-onnx==2.0.1, vosk==0.3.45, sounddevice==0.5.6, numpy==2.5.5, psutil==7.2.2, piper-tts==1.8.0; ONNX CPU. The B module deliberately does not vendor A's canonical dataclasses: imported at integration time from A's branch (draft PR #8). No paid models, adaptation, retries, or new always-on services.

Upstream model/license references:
- https://k2-fsa.github.io/sherpa/onnx/pretrained_models/online-ctc/t-one-ctc-models.html
- https://alphacephei.com/vosk/models
- https://k2-fsa.github.io/sherpa/onnx/pretrained_models/offline-transducer/zipformer-transducer-models.html
- https://huggingface.co/alphacep/vosk-model-small-ru

GigaAM CTC was considered but excluded pending license review because published GigaAM model families include noncommercial licensing restrictions; production cannot silently substitute it.

Verified SHA256:
- T-one model.onnx: 5ded080e2a6c86ecc11bc0902d77524eb3e8b0844cb0c0754347f5aafb4dabc
- Small Zipformer encoder.int8.onnx: 75653125bf3621d86a2b140ffd84a1c3b7610fc8cd49f2b6d70cf5786be0d085
- Vosk am/final.mdl: 36d67b53dc90d96ea48097f9e17e7c5937689ad76cb8bed25091317bbaf25919

## Measured PLAN results: 2026-11-16

Sequential 1-thread offline benchmark on AMD Ryzen 7 7840HS. The SAME PCM was used for each engine. Synthetic result columns below are v2 (8 positives + 8 negatives, no natural voice), and public column uses three public natural-speech negatives. RTF = inference wall time / total replay audio; it is not wake latency. Peak RSS includes Python+model, not just weights.

| Model | Public natural speech negatives | Synthetic positives/negatives | Cold ms (public/synthetic) | RTF (public/synthetic) | CPU cores eq. (public/synthetic) | Peak RSS MB (public/synthetic) |
|---|---|---|---|---|---|---|
| T-one | FP 0/3 | TP 0/8; FP 0/8 | 2026/2940 | 0.113/0.183 | 0.988/0.889 | 367.5/364.7 |
| Vosk | BLOCKED OOV | NOT_RUN | n/a | n/a | n/a | n/a |
| Zipformer window | FP 0/3 | TP 0/8; FP 0/8 | 2323/2188 | 0.141/0.135 | 0.999/0.991 | 158.0/159.2 |

Vosk direct vocabulary lookup: gobot [гобот] = -1, gabot [габот] = -1; grammar forcing is NOT proof of vocabulary support. A diagnostic synthetic single utterance "Гобот какая сегодня погода" yielded T-one text "вот какая сегодня погода" and Zipformer window an intermediate "да вот какая сегодня погода" — both lost the name. Critically, synthetic negative "Вот какая сегодня погода" also yielded EXACTLY "вот какая сегодня погода" with T-one: aliasing the very common word "вот" as GoBot would be unsafe. Synthetic negatives now also include "Эй робот" and "Привет работа". No fuzzy alias was enabled.

Public dataset hash: 7869291bf875db2d6d7de19afe4a45c24b7f7ffd5d232502c459a4bb63b70f73
Synthetic v2 dataset hash (8 positives + 8 negatives): 8fa4541303880ffa78712ca0490f64496ce2d45e939eb38ca80083a5f4516d46
Reports: public-three-models.json and synthetic-v2-three-models.json under external results folder. Original v1 synthetic-three-models.json with 8 positives + 5 negatives is retained as a historical control (v1 hash 5a951802ee3a5d1fd5868e5b6a8a4e5c6fda3a28661d09a97364baf0e365fe6b). Neither private recordings nor models committed.

P50/P95 measured: **NOT_MEASURED** (no accepted positives or annotated human name offsets). False wakes/hr: **NOT_MEASURED** (background exposure far less than 30 minutes; test negatives do not include real television playback). Real PC mic: NOT_RUN. The synthetic results are NOT evidence of human performance.

## Reproduce from PLAN PowerShell, no mic

~~~powershell
Set-Location 'C:\Users\PLAN\gobot\GoBotHome-wake-lab'
$py = 'C:\Users\PLAN\gobot\HOST-B-lab\.venv\Scripts\python.exe'
$models = 'C:\Users\PLAN\gobot\HOST-B-lab\models'
$lab = 'C:\Users\PLAN\gobot\HOST-B-lab'
& $py -m unittest discover -s tests -p 'test_host_wake_lab_*.py' -v
& $py -m services.voice.host_wake_lab.harness --manifest "$lab\fixtures\manifest_public.json" --models-root $models --out "$lab\results\public-retest.json" --engines t-one vosk zipformer-window --threads 1
& $py -m services.voice.host_wake_lab.harness --manifest "$lab\fixtures\synthetic\manifest_synthetic.json" --models-root $models --out "$lab\results\synthetic-retest.json" --engines t-one vosk zipformer-window --threads 1
& $py -m services.voice.host_wake_lab.live --list-mics
~~~

## Local opt-in PC mic and deterministic voice smoke

**This command has NOT been run with microphone capture.** Run only with Owner physically present and a test window coordinated with HOST-A. It requires an in-terminal typed YES-PC-MIC in addition to the CLI flag; no background agent may type it. Device 21 is an identified PLAN 16 kHz microphone input, but verify the actual input at test time.

~~~powershell
Set-Location 'C:\Users\PLAN\gobot\GoBotHome-wake-lab'
$py = 'C:\Users\PLAN\gobot\HOST-B-lab\.venv\Scripts\python.exe'
& $py -m services.voice.host_wake_lab.live --engine t-one --models-root 'C:\Users\PLAN\gobot\HOST-B-lab\models' --device 21 --seconds 90 --owner-consent-live --piper-model 'C:\Users\PLAN\gobot\GoBotHome\data\models\vits-piper-ru_RU-denis-medium\ru_RU-denis-medium.onnx'
~~~

After real wake, try "Гобот который час?" or "Гобот поставь таймер на 3 минуты" naturally, no pause after name. The local demo accepts timers **only up to three minutes** and, after mic capture ends, waits for the finite local timer to ring (or logs explicit cancellation), rather than falsely claiming a daemon timer survived process exit. Successful local deterministic response is **not** proof of an LLM conversation. If wake recognition fails, no false synthetic ACK is permitted. A local test does not authorize paid B/C/CLI, gateway integration, device flashing, or a production switch.

## Controlled human phrase benchmark (prepared, consent NOT granted)

Run this IN A VISIBLE LOCAL PLAN TERMINAL, with Owner physically present. It will not open the mic unless Owner uses BOTH the explicit CLI flag and typed YES-PC-MIC, then manually presses Enter per test. **It has NOT been executed on a human voice yet.**

~~~powershell
Set-Location 'C:\Users\PLAN\gobot\GoBotHome-wake-lab'
$py = 'C:\Users\PLAN\gobot\HOST-B-lab\.venv\Scripts\python.exe'
& $py -m services.voice.host_wake_lab.guided_live --owner-consent-live --models-root 'C:\Users\PLAN\gobot\HOST-B-lab\models' --device 21 --engine t-one --shadow-engine zipformer-window --rounds 1 --trial-seconds 4 --include-tv-negative
~~~

The CLI displays **8 positive** natural phrase prompts, **5 near-negative** prompts and, with optional flag, a 30-second **real TV** negative trial. Owner confirms after each actual utterance; skipped/unconfirmed trials do NOT contribute denominators. T-one is processed LIVE as mic PCM arrives. Once the mic is closed, identical ephemeral in-memory PCM is replayed to the Zipformer shadow decoder. Each buffer is zeroed after replay. No raw audio or ASR transcripts are written. The report saves only manual prompt ID, phrase ID of candidates, confirmed positives/misses, negative false events, model/cpu/RAM and frame backlog; stored only in C:\Users\PLAN\gobot\HOST-B-lab\results\guided-human-meta-*.json outside Git.

This is **real human self-confirmed trial accuracy**, not independently acoustically verified speech; Zipformer shadow replay is not a live latency benchmark. Neither p50/p95 from *end of spoken wake name* nor false wakes/hour may be reported without independent name-end annotation and >=30 minutes genuine negative exposure. No session, model retraining, external provider, second permanent Brain or hardware gateway is started. Up to 300 cumulative seconds of bounded mic capture per explicit local run, then stream closes.

**No auto-integration:** if human samples still miss, keep MODEL_NOT_ACCEPTED, do not widen to untested fuzzy aliases or spend paid quotas. To test paid actual conversation later, obtain separate Owner grant and let HOST-A use its existing Brain admission path; HOST-B provides only detector events.

## First real human attempt on PLAN and corrected confirmation UI (16 November 2026)

An actual Owner-run live guided microphone result was found at 18:40 local time:
`C:\\Users\\PLAN\\gobot\\HOST-B-lab\\results\\guided-human-meta-20261116T214004Z.json`. It is retained only on PLAN, not committed or uploaded. T-one live primary and Zipformer same-PCM shadow each recorded **0 correct wakes out of 5 Owner-confirmed positive trials** and **0 false events out of 5 confirmed negative trials**. Three positive prompts were **absent from the saved denominator**: `hello-gobot`, `gabot-weather`, `gobot-time`. Whether skipped or excluded because Enter was pressed during y/n confirmation cannot be recovered: the original runner did not save exclusion reasons. There was no TV trial and no measured microphone signal level. Audio was not persisted, so it is impossible to verify voice clarity from the old report. These results are real Owner-confirmed trials, not independent acoustic transcription; the detector is still **NOT_ACCEPTED**.

Updated runner now accepts `y`, `yes`, `да` for confirming a completed trial; `n`, `no`, `нет` exclude. At the *confirmation* prompt, blank Enter **re-prompts rather than silently skipping**; at the *start* prompt Enter starts recording. It records explicit skipped/excluded prompt IDs and only numerical RMS/peak dBFS as an input-level diagnostic (no PCM/transcripts). It still demands separate local typed `YES-PC-MIC` authorization. You can repeat just the three missing prompts using the following local file (not committed):

`C:\\Users\\PLAN\\gobot\\HOST-B-lab\\RETRY_3_WAKE_TEST.cmd`

This opens the microphone only after local Owner consent, for at most three 8-second prompts (24 seconds total), and writes a *new* metadata-only JSON without overwriting the prior result. It does not run the background-TV test or ask paid models. At this point, no new real mic capture has been initiated by HOST-B.

## HOST-A handoff gate

1. Use bridge.py / HostWakeDetectorAdapter with the A-owned services/voice/host_wake_contract.py (published in HOST-A draft PR #8). The input fields are pcm_s16le, stream_epoch, sample_index, received_monotonic_ns. The output is WakeEvent with detected_monotonic_ns. B does not vendor contract types.
2. Keep activation_approved=False (shadow feed_chunk returns None) until Owner accepts human trials and false-positive exposure. No automatic merge to master.
3. Current benchmark verdict **NOT_ACCEPTED**. Among tested candidates, T-one is the best *starting point* for future human evaluation because it is genuine Russian native streaming — not a pass.
