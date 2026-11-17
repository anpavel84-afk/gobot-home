# GoBot HOST-B / WakeNet10 RU technical build evidence

Report date: 16–17 November 2026. Owner directive: Issue #6.
Scope: independent engine proof-of-concept and future source handoff, NOT a
working Monika wake binary for the installed Spotpear.

**Latest OWNER DIRECT Issue #5 comment #6935913449:** only HOST-A and HOST-B exist. HOST-A has exclusive ownership of ALL computer-side wake/local/cloud STT, Brain and hardware integration. HOST-B scope here is strictly ESP_LOCAL / WakeNet10 model research, prototype source, build and published handoff. No new HOST-D branch or parallel B-side PC wake work.

## What was independently checked

1. Actual installed Spotpear: ESP32-S3 rev0.2; 16 MiB Flash; 8 MiB PSRAM;
   firmware 0.4.13-dev-host-a-rc1-r3 previously installed by HOST-A. H0
   preserved. HOST-A independently owns the I2S/ES8311/AEC/Opus/Wi-Fi/COM3
   and gateway; none were accessed or modified by this research.
2. Exact HOST-A pinned build image: espressif/idf:v6.0.1,
   SHA256 efc19fae2f52fc6873630c668da26aa834139a063b5fb73a46ebc0dbd217b587.
   Independent builder image digest matched. Registry component lock resolved
   ESP-SR 2.6.2 with component hash
   31c301aa50346158c85271b149a6c7473dfdf3edaa0958968f9cdfe06d4dcd45,
   ESP-DL 3.3.13, dl_fft 0.8.0, cjson 1.7.19~2, ESP New JPEG 1.0.2.
   The exact complete lockfile is committed as dependencies.lock.
   ESP-SR version integrated in CURRENT A firmware has NOT been established;
   no requirement to update A firmware or SDK arises from this build.
3. Upstream official Espressif esp-sr repository checkout HEAD
   bb552f1a559396a17681299cb3e199a0f1a4520a,
   whose idf_component.yml declares 2.6.2. Registry package (not a
   nonexistent v2.6.2 GitHub tag) was used in actual build.
4. Official model chosen: wn10_ru_privetesp, the Russian "Привет ESP"
   DEMO ONLY. No model for the distinct requested name "Мо́ника" found in
   upstream wakeword_list.md (generated 2026-11-11).
   Official Russian files (unpacked) total 804,996 bytes including two
   alternative coefficient datasets, while generated selected packaged
   srmodels.bin is 378,634 bytes. This is not a Monika model.
5. True private 16MiB H0 partition descriptor table was read from 0x8000
   on the Windows PLAN PC in read-only mode, not from UART:
      nvs 0x9000 size 0x4000
      otadata 0xD000 size 0x2000
      phy_init 0xF000 size 0x1000
      ota_0 0x20000 size 0x3F0000 (4,128,768 bytes)
      ota_1 0x410000 size 0x3F0000
      assets 0x800000 size 0x800000
      model partition: NONE.
   Existing r3 app occupies 3,047,680 of 4,128,768 bytes; nominal
   1,081,088 bytes free is APP capacity, not a model data partition.
   There is no direct empty flash region to place a model partition
   with unchanged NVS/OTA/assets.
6. Standalone PoC source and compiler confirmed genuine ESP32-S3 binary
   and model partition packing, using ESP-IDF 6.0.1 inside an isolated
   Docker container on authorized Linux build machine. NO physical UART,
   serial, display, mic, NVS, OTA, production gateway or flash call.

## Real reproducible isolated compilation and exact artifacts

Builder: isolated directory on connected Linux test server, pinned
espressif/idf:v6.0.1 image. Commands:

    idf.py set-target esp32s3
    idf.py build
    idf.py size

Exit status: SUCCESS; exactly 1187/1187 Ninja build steps completed.
Check_sizes script: app 0x8ec10 bytes, smallest standalone app partition
0x400000 bytes, free 0x3713f0 bytes (86% of standalone app slot).
esptool image-info PASS, header ESP32-S3, Flash16MB, DIO/80MHz, valid hash.
The proposed RC1 partition CSV was separately parsed/validated using the
official gen_esp32part.py; it was NEVER written to Flash.

Private artifact sizes and full SHA256:
- app.bin 584,720 B:
  37c788ff1b1ec1f33dc3e11aaecbd15232bbf036e4bb87bb531ae79dd83145bf
- model srmodels.bin 378,634 B:
  137fbde80079b3c755f21222021ffa0edabceb43059e45e3e6e51b0359163b1d
- standalone partition-table.bin 3,072 B:
  eba912fa9636217976fd5b1e10ef4a32d932d957e96ac50e5f919322d0ad767c
- ESP32-S3 PoC ELF 16,777,180 B on isolated Linux staging only:
  877c370f75488bb86d1284accfb02fffb989e930b7cb69fbbe4dd22a9ed5d745.

These three essential PRIVATE binaries (app, model, standalone partition table)
were copied without an Internet file-sharing endpoint to:
C:\Users\PLAN\gobot\HOST-B-lab\wakenet10-build-private
Windows PLAN verified all three destination hashes against builder SHA256
and removed temporary base64 transfer files. ELF remains private on isolated
builder and is NOT needed for any current user task.

Public source-equivalence SHA256 (Linux build vs Windows public source):
- main/main.c:
  7d3cdcb906f7c57afc056ecc3fdbdf71b40717a354bae41f0fb6d0c65f03d566
- sdkconfig.defaults:
  6f74b18561c750b09739bffeae5807c23d6df016bddea975da111edb90970c60
- dependencies.lock:
  6411359731c7d21e281530c9d9f24a71093b730926b57a7cd3080cac14319269

Model was packaged by official build as:
  ESP-SR Models Report: wn10_ru_privetesp (369.64 KiB).

No binary, model weight, private backup, device identity, NVS, credentials
or recorded audio is included in the GitHub branch.

## CPU / RAM / PSRAM evidence, and limitations

- Compiler static size for THIS standalone PoC: ESP-IDF size reports
  DIRAM 75,009 bytes used in the 341,760-byte region, 266,751 remaining.
  That does NOT measure model runtime allocations or combined HOST-A use.
  App bin 584,720 B, packed model 378,634 B, proposed model partition
  2,097,152 B. Does NOT estimate the future combined RC1-r3 app binary.
- Official published ESP32-S3 3-channel reference (different channel mode):
  WakeNet10 internal RAM 17KB, PSRAM 523KB, 7.1ms/32ms frame, 22.6%
  one-core CPU. This is an EXTERNAL reference, not measured on our Spotpear.
- POC includes runtime instrumentation for one-channel DET_MODE_90:
  cold create latency, actual rate/channels/native chunk, internal/PSRAM
  free delta, synthetic zero-PCM feed processing time/cpu percentage.
  These code paths COMPILED but were NEVER EXECUTED ON ACTUAL ESP32-S3.
  Thus actual 1-channel CPU/RAM/PSRAM on this hardware: NOT_MEASURED.
- AEC, ES8311, Opus producer, Wi-Fi and LVGL coexistence:
  only the interface/contract has been verified syntactically and with
  native source-switch tests; no unified RC1 firmware image was produced
  or runtime-measured. No second I2S-reader must be introduced.

## Layout and application-only upgrade analysis

Two distinct source CSVs:

- partitions_poc.csv: standalone, independently built factory-app +
  model partition, safe only as a developer POC layout, NOT for current
  live Spotpear and NOT H0-compatible.
- partitions_proposal_rc1_NOT_FOR_FLASH.csv: a mathematical alternative
  that preserves both existing OTA regions, but shrinks assets from 8MiB
  to 6MiB and adds a 2MiB model partition at 0xE00000. Verified the CSV
  with Espressif's gen_esp32part.py (EXIT 0). NOT compatible with immutable
  asset contents unless HOST-A separately proves a lossless migration;
  new partition table would require a distinct flash operation and Owner
  permission. DO NOT INSTALL.

Question "full MONIKA app-only binary without modifying current partition
table?" Answer: NOT PROVEN. Full A RC1 integration is NOT BUILT and the
official model-loader path requires a "model" data partition that does
not exist. Alternatives such as loading from external paths/assets/embedded
model must be independently designed, footprint-tested and explicitly
approved. NEVER claim 1,081,088B app slack provides reserved model storage.

## Proposed HOST-A integration files

- main/main.c: tested standalone RU WakeNet10 model engine (demo only).
- integration/pcm_tap_gate.hpp: a code-only model-source gate that defaults
  to PLAN_STREAM and permits switching to ESP_LOCAL_WAKENET10 only at IDLE,
  with no playback/STOP/mute pending and at most one activation; re-chunks
  existing A 960-sample producer without new I2S reader.
- integration/test_pcm_tap_gate.cpp: native C++17 regression compiled
  with -O2 -Wall -Wextra -Werror and EXECUTED PASS on isolated builder.
- integration/CONTRACT.md: A-owned future protocol must implement
  authenticated gobot_host_local_wake event with source/epoch/generation
  provenance, not disguised gobot_host_touch, shared pre-roll and existing
  HostCore activation. RC1-r3 does NOT support this message.
- ESPRESSIF_CUSTOM_MODEL_REQUEST.md: unsent outreach to sales@espressif.com.
- dependencies.lock + project configs + two NON-FLASH CSV alternatives.

These must be reviewed and selectively integrated by HOST-A, which owns
the actual device, codec, gateway, flash and firmware source. Do not
merge this branch or flash it directly.

## Price / license / Monika weight gap

Official public supported wakeword list contains no named "Мо́ника" model.
Official Espressif customization offers TTS-only, TTS-plus-collected data,
and provided-dataset options. TTS-only can avoid personal voice samples.
Public documentation says one-time customization fee rather than annual or
per-device royalties, but **no published exact fixed price/lead time for
Russian Monika**. Quote, model rights, commercial shipping redistribution,
technical performance and availability of a free evaluation must be
confirmed in writing from sales@espressif.com before spending or sharing
speech. Draft prepared, not sent. No verified free self-service Russian
WakeNet10 model-training tool.

No weight named Monika was trained, obtained, purchased, renamed, embedded
or claimed. Demo still is "Привет ESP".

## Explicit release matrix

| Gate | Verified outcome |
| --- | --- |
| SOURCE_IMPLEMENTED | YES for standalone WakeNet10 RU demo and native source-switch proposal; NO for complete merged RC1 code |
| BUILT | YES for separate ESP-IDF PoC demo app and official packed model; NO for integrated RC1+WakeNet |
| MODEL_AVAILABLE | YES official "Привет ESP"; NO official "Мо́ника" |
| FREE_TESTED | CMake/ESP-SR build, native C++ gate, esptool image and partition CSV validation PASS |
| INSTALLED | NO; zero flash/OTA/COM3/device interactions |
| HUMAN_ACCEPTED | NO; no new ESP32-S3 on-device wake/CPU/audio trials |
| PRODUCTION_GATEWAY | Left unchanged with PLAN_STREAM Monika; no paid calls |

Official links:
https://github.com/espressif/esp-sr
https://github.com/espressif/esp-sr/blob/master/wakeword_list.md
https://docs.espressif.com/projects/esp-sr/en/latest/esp32s3/wake_word_engine/README.html
https://docs.espressif.com/projects/esp-sr/en/latest/esp32s3/flash_model/README.html
https://docs.espressif.com/projects/esp-sr/en/latest/esp32s3/benchmark/README.html
https://docs.espressif.com/projects/esp-sr/en/latest/esp32s3/wake_word_engine/ESP_Wake_Words_Customization.html

NO pay, no mic recording, no physical device interaction, no second supervisor,
no new ongoing service, no production deployment, no master merge.
