# GoBot HOST-B · offline WakeNet10 RU ESP32-S3 engineering proof

**OWNER DIRECT 2026-11-16 / Issue #5 comment #6935913449: EXACTLY TWO DIRECTIONS.** HOST-A exclusively owns PC-side wake, local Vosk/T-one diagnostics, approved future cloud STT, Brain and the installed firmware. HOST-B owns ONLY this independent ESP_LOCAL / WakeNet10 research. No HOST-D executor or branch. **NOT the installed Spotpear firmware and NOT the wake word «Мо́ника».**
This self-contained ESP-IDF application performs an OFFLINE compile-time
verification of Espressif's official Russian WakeNet10 demo
`wn10_ru_privetesp` (**"Привет ESP"**) using exactly one microphone channel
in direct-mode `DET_MODE_90` with signed mono 16 kHz PCM. It DOES NOT open
I2S on any board: the standalone app feeds synthetic zero-PCM for a
future bounded runtime benchmark, should a separate development board
ever be authorized. It has no Wi-Fi, gateway, Brain, touch, TTS, audio
recording or flashing command.

## Verifiable toolchain

- CPU target: **ESP32-S3** with 16 MB Flash and 8 MB octal PSRAM config.
- Pinned builder: **espressif/idf:v6.0.1**, Docker SHA-256:
  `efc19fae2f52fc6873630c668da26aa834139a063b5fb73a46ebc0dbd217b587`.
- **ESP-SR 2.6.2** via IDF Component Registry, checksum pinned in
  `dependencies.lock`; ESP-DL 3.3.13, dl_fft 0.8.0.
- `CONFIG_SR_WN_WN10_RU_PRIVETESP=y`; no model claim for Monika.
- Isolated test has dedicated model partition 2 MB (not the real board).
- CMake source under `main`; compiled metrics recorded in separate build
  report, but **do not confuse compilation or images with MCU execution**.
- No firmware or model weights in GitHub. Private build outputs are retained
  only outside source control.
- Reproducible command (on an isolated developer machine with the pinned
  Espressif toolchain; MUST NOT flash the installed device):

~~~shell
idf.py set-target esp32s3
idf.py build
# Never run "idf.py flash" or "idf.py app-flash" against the live Spotpear.
~~~

The POC's `main.c` verifies that the requested model name is the official
demo, that the runtime API advertises 16k samples/sec and exactly one input
channel, and that native model frame sizes are bounded before PCM is passed
into the official WakeNet detect function. It logs internal/PSRAM allocation
deltas and CPU timing **only when executed on an authorized isolated dev
board**. This actual on-board measurement has NOT been performed.

## Exact existing real partition map — read-only H0 backup

Obtained by parsing the ESP-IDF partition descriptors at flash offset 0x8000
from the existing 16 MiB *private readback on PLAN*; no COM3 access:

| Partition | Offset | Size |
|--|--:|--:|
| nvs | 0x9000 | 16,384 B |
| otadata | 0xD000 | 8,192 B |
| phy_init | 0xF000 | 4,096 B |
| ota_0 | 0x20000 | 4,128,768 B |
| ota_1 | 0x410000 | 4,128,768 B |
| assets | 0x800000 | 8,388,608 B |
| **model** | missing | **0 B** |

Installed RC1-r3 app: 3,047,680 B of ota_0 (4,128,768 B);
1,081,088 B nominal free app partition capacity. The app area is NOT
a reserved ESP-SR model partition. The current no-free-gap partition layout
cannot directly receive `srmodels.bin` without a new model-storage design.

`partitions_poc.csv` is solely for separate standalone test firmware.
`partitions_proposal_rc1_NOT_FOR_FLASH.csv` is a **calculation only**:
keeps OTA boundaries, reduces assets by 2 MB and allocates that space as a
model partition. This changes existing device data placement, cannot be
flashed under current permissions, and needs inventory and lossless asset
migration plus separate approval. **Do not change NVS, bootloader, OTA,
partition table, assets or installed firmware from HOST-B.**

## Future integration: single audio producer, one wake source

See `integration/CONTRACT.md` and
`integration/pcm_tap_gate.hpp` (the latter has host-native test
`integration/test_pcm_tap_gate.cpp`). They provide the source switch
`PLAN_STREAM` vs `ESP_LOCAL_WAKENET10` and bounded PCM sample re-chunking
from HOST-A's existing 16kHz mono capture producer, **not an additional
ES8311/I2S reader**.

No second AEC or competing Opus producer may be added. The server remains
responsible for pre-roll/response/STOP. Existing RC1-r3 HOST-A currently
DOES NOT support a device-originated `gobot_host_local_wake` message.
Adding it to the authenticated HOST-A listener and mapping it to the
**existing** HostCore activation requires A-owned review and a separate
controlled future install. Faking a physical touch event would lose
provenance and is forbidden.

## Model customization

**No official public `wn10_ru_monika` weights confirmed.** The source
`wn10_ru_privetesp` detects a different word and must never count as a
Monika model or be activated as one. Official customization inquiries:
sales@espressif.com. The draft request is in
`ESPRESSIF_CUSTOM_MODEL_REQUEST.md` — NOT sent and no payment/recordings
authorized. Espressif's public policy indicates a one-time training cost
and no per-device/annual license fee, without a fixed public price. TTS-only
training is an option that does not need personal recordings. Russian
self-service training tooling is not publicly verified.

Official sources:
- https://github.com/espressif/esp-sr
- https://github.com/espressif/esp-sr/blob/master/wakeword_list.md
- https://docs.espressif.com/projects/esp-sr/en/latest/esp32s3/wake_word_engine/README.html
- https://docs.espressif.com/projects/esp-sr/en/latest/esp32s3/flash_model/README.html
- https://docs.espressif.com/projects/esp-sr/en/latest/esp32s3/benchmark/README.html
- https://docs.espressif.com/projects/esp-sr/en/latest/esp32s3/wake_word_engine/ESP_Wake_Words_Customization.html

## Release status gate

SOURCE_IMPLEMENTED=POC/CONTRACT; MODEL_AVAILABLE_DEMO=YES;
MODEL_AVAILABLE_MONIKA=NO; BUILT=only if build manifest independently
confirms .elf/.bin and packed official model; FREE_TESTED=component
dependencies/native gate/compile only; INSTALLED=NO; HUMAN_ACCEPTED=NO;
PRODUCTION_MONIKA_SOURCE=PLAN_STREAM unchanged. Do not merge or enable
the experimental ESP branch without explicit HOST-A owner review.
