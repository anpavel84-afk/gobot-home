# GoBot HOST-B — Russian Wake Recognition Lab (#6)

**Current gate: SOURCE_IMPLEMENTED / FREE_TESTED / MODEL_NOT_ACCEPTED.**
PC_MIC_HUMAN_ACCEPTED=NOT_RUN_CONSENT_REQUIRED; BOARD_HUMAN_ACCEPTED=NOT_RUN_HOST_A_ONLY; PAID_CALLS=0.

This is an isolated host-only research implementation, not a production wake module. It does not modify the HOST-A gateway, Opus path, firmware, active Brain, running workers, system Python, or the canonical PCM/WakeEvent contract. Its separate Git worktree is feat/host-wake-lab, based on the verified 64ba27e2 (descendant of H0 bf8a2e98), never the stale a31674e.

## API and safety

- detect.py: WakeLab.feed(pcm_s16le, stream_epoch, sample_index, receive_monotonic, speaking=False) consumes mono s16le PCM16 at 16 kHz and returns a list of WakeEvent dictionaries (stream_epoch, end_sample_index, phrase_id, detector_id, confidence or null, detected_monotonic).
- bridge.py: ShadowWakePort.feed_audio_chunk takes the future HOST-A-owned AudioChunk mapping/object, keeping A's contract as source-of-truth. Activation callback is **off by default**, regardless of detection. HOST-A may enable only after acceptance.
- engines.py: native streaming T-one 8 kHz with private 16→8 FIR; small Vosk 16 kHz fails closed on OOV, Zipformer RU is **offline rolling-window**, not native streaming.
- Strict continuity across sample_index and stream_epoch, two spaced ASR updates before event, one event per segment, no forced one-word grammar/fuzzy aliases.
- live.py: no mic until Owner locally types YES-PC-MIC after an explicit CLI flag and warning. Bounded run; no PCM/transcript writes; no network. One local PC speaker earcon and optional time/timer via deterministic local_command.py + pre-existing read-only Piper Russian TTS.
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

Runtimes: Python 3.14.4 isolated; sherpa-onnx==2.0.1, vosk==0.3.45, sounddevice==0.5.6, numpy==2.5.5, psutil==7.2.2, piper-tts==1.8.0; ONNX CPU. No paid models, adaptation, retries, or new always-on services.

Upstream model/license references:
- https://k2-fsa.github.io/sherpa/onnx/pretrained_models/online-ctc/t-one-ctc-models.html
- https://alphacephei.com/vosk/models
- https://k2-fsa.github.io/sherpa/onnx/pretrained_models/offline-transducer/zipformer-transducer-models.html
- https://huggingface.co/alphacep/vosk-model-small-ru

GigaAM CTC was considered but excluded due to noncommercial licensing restrictions in published GigaAM models; production cannot silently substitute it.

Verified SHA256:
- T-one model.onnx: 5ded080e2a6c86ecc11bc0902d77524eb3e8b0844cb0c0754347f5aafb4dabc
- Small Zipformer encoder.int8.onnx: 75653125bf3621d86a2b140ffd84a1c3b7610fc8cd49f2b6d70cf5786be0d085
- Vosk am/final.mdl: 36d67b53dc90d96ea48097f9e17e7c5937689ad76cb8bed25091317bbaf25919

## Measured PLAN results: 2026-11-16

Sequential 1-thread offline benchmark on AMD Ryzen 7 7840HS. The SAME PCM was used for each engine. RTF = inference wall time / total replay audio; it is not wake latency. Peak RSS includes Python+model, not just weights.

| Model | Public natural speech negatives | Synthetic positives/negatives | Cold ms (public/synthetic) | RTF (public/synthetic) | CPU cores eq. (public/synthetic) | Peak RSS MB (public/synthetic) |
|---|---|---|---|---|---|---|
| T-one | FP 0/3 | TP 0/8; FP 0/5 | 2026/2077 | 0.113/0.155 | 0.988/0.996 | 367.5/364.0 |
| Vosk | BLOCKED OOV | NOT_RUN | n/a | n/a | n/a | n/a |
| Zipformer window | FP 0/3 | TP 0/8; FP 0/5 | 2323/2510 | 0.141/0.164 | 0.999/1.002 | 158.0/157.6 |

Vosk direct vocabulary lookup: gobot [гобот] = -1, gabot [габот] = -1; grammar forcing is NOT proof of vocabulary support. A diagnostic synthetic single utterance "Гобот какая сегодня погода" yielded T-one text "вот какая сегодня погода" and Zipformer window text "да вот какая сегодня погода" — both lost the name.

Public dataset hash: 7869291bf875db2d6d7de19afe4a45c24b7f7ffd5d232502c459a4bb63b70f73
Synthetic dataset hash: 5a951802ee3a5d1fd5868e5b6a8a4e5c6fda3a28661d09a97364baf0e365fe6b
Report JSONs: public-three-models.json and synthetic-three-models.json under external results folder. Neither private recordings nor models committed.

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

After real wake, try "Гобот который час?" or "Гобот поставь таймер на 3 минуты" naturally, no pause after name. Successful local deterministic response is **not** proof of an LLM conversation. If wake recognition fails, no false synthetic ACK is permitted. A local test does not authorize paid B/C/CLI, gateway integration, device flashing, or a production switch.

## HOST-A handoff gate

1. Use bridge.py and detect.py only as an isolated importable experiment. A owns the canonical contract and production side.
2. Keep callback disabled (shadow) until Owner accepts human trials and false-positive exposure. No automatic merge to master.
3. Current benchmark verdict **NOT_ACCEPTED**. Among tested candidates, T-one is the best *starting point* for future human evaluation because it is genuine Russian native streaming — not a pass.
