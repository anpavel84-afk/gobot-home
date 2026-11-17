# HOST-B ESP_LOCAL microWakeWord «Мо́ника»

**OWNER DIRECT: local training from scratch is now permitted**. The
previously rejected GoBot custom model was used only as read-only
engineering reference. The active PC Vosk/Live-Transcribe/Brain path
remains exclusively HOST-A's responsibility. This is a separate **ESP_LOCAL**
research branch, with no third HOST-D direction.

## Actual training status — V1 / V2 / V3

**Three actual CPU-trained INT8 models exist, and ALL THREE were rejected by independent synthetic wake-quality tests.** None should be flashed or marked HUMAN_ACCEPTED. V1 39/55 positives with 35 false events/100 negatives; V2 45/70 with 57 false/150; V3 tested at validation-only selected threshold 255 had 29/62 Elena positives with 9 false/150, and 4/56 on new Aleksandr-HQ profile with 4 false/125. See [RESULTS_V1_V2_V3_2026-11-17.md](RESULTS_V1_V2_V3_2026-11-17.md) and [PUBLIC_MODEL_COMPARISON.json](PUBLIC_MODEL_COMPARISON.json).

All three weight files have been SHA-verified on Windows PLAN under separate private v1, v2, v3 folders. Two separate standalone ESP-IDF 6.0.1 builds succeeded with embedded V1 and V3 weights, but no combined RC1-r3 image or human/physical acceptance exists. The old GoBot model/H0 remain read-only.

## Actual first model and privacy

- `synthesize.py`: fully new Russian TTS corpus, speaker-disjoint
  train/validation/test, phonetic hard negatives, immediate connected
  question prompts. Uses the old CPU-only Piper/RHVoice/espeak executables
  READ-ONLY; audio is newly synthesized under an isolated training root.
- `train_monika.py`: real microWakeWord MixedNet TF2.18 CPU training,
  stable feature frontend, training checkpoint selection on heldout voice
  validation and true INT8 streaming export.
- `evaluate_heldout.py`: actual TFLite stream replay, threshold selected
  on the validation voice BEFORE ever scoring the test voice; false events
  and missing wake detections reported separately.
- `synthesize_v2.py`, `train_monika_v2.py`: second experimental
  hard-negative iteration; never overwrite prior corpus/model/results.
- `esp32_standalone/`: isolated ESP-IDF6.0.1 ESP32-S3 TFLite-Micro
  proof-of-concept; its private `main/monika_int8.tflite` is injected
  only in the CPU build directory. It does not include ESP32 I2S
  drivers and has NO device install script.

The v1 private weights reside at:
`C:\Users\PLAN\gobot\HOST-B-lab\monika-mww-private\v1\monika_int8.tflite`

See [RESULT_V1_2026-11-17.md](RESULT_V1_2026-11-17.md) for the verified
and **failed** strict independent wake quality results. Any successor
model must be tested separately before selection.

## Reproduce with existing free preinstalled CPU toolchain

On an AUTHORIZED isolated Linux training host, never in a service that
owns HOST-A, no cloud APIs or GPU. Inputs point to an existing older
toolchain path *READ ONLY*. The new corpus, model and evaluation output
directories must NOT preexist.

```sh
export CUDA_VISIBLE_DEVICES=-1 TF_NUM_INTRAOP_THREADS=2 OMP_NUM_THREADS=2
export PYTHONPATH=/opt/gobot-firmware/20261112-gobot-v1/wake-stage/mww:$PWD
/opt/gobot-firmware/20261112-gobot-v1/wake-stage/env/bin/python \
    synthesize.py --old-tools /opt/gobot-firmware/20261112-gobot-v1/wake-stage \
    --output NEW-CORPUS --positives 55 --negatives 100
/opt/gobot-firmware/20261112-gobot-v1/wake-stage/env/bin/python \
    train_monika.py --corpus NEW-CORPUS --output NEW-MODEL \
    --steps 1500 --windows 8192
/opt/gobot-firmware/20261112-gobot-v1/wake-stage/env/bin/python \
    evaluate_heldout.py --corpus NEW-CORPUS \
    --model NEW-MODEL/monika_int8.tflite --output NEW-REPORT
```

Source + reports (but NO raw audio, models, paid cloud credentials,
input transcripts, H0, private NVS, SDK caches or firmware binaries)
are safe for the HOST-B GitHub branch. Models are deliberately kept
private on PLAN until human/device acoustic acceptance.

## How HOST-A may later integrate

Use only the existing ES8311/I2S single microphone PCM producer. Feed
the same 16k mono int16 samples to microWakeWord frontend and to the
existing Opus/network pipeline. Never start a second I2S reader.
TFLM gets 40 features every 10ms, produces an INT8 3x40 input block
every 30ms and UINT8 wake probability. Use a bounded sliding window,
one idle-only source selection and suppression during speaking/Stop.
The TFLite runtime needs reserved PSRAM tensor arena and resource
variables (original old device runtime used 128KiB PSRAM arena, 2KiB
variables), to be remeasured with new model on device. A must own
the authenticated local `gobot_host_local_wake` event, 2s RAM
pre-roll, and all response/UX/Stop integration. No flashing without
separate express Owner authorization.

Not installed. Synthetic evaluation is NOT human or TV false/hr
acceptance. Full HOST-A RC1 integration not built yet.
