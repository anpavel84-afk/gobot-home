# HOST-B Sophia app-embedded WakeNet10 — build evidence and handoff

Date: 2026-11-17. Owner issue #6 / draft PR #12.
HOST-B ESP_LOCAL ONLY. HOST-A independently owns all PC wake/browser, Brain,
physical ESP32/Spotpear, COM3, gateway, actual RC1-r3 firmware and flashing.

## Baseline official Sophia standalone model-partition build

ESP-IDF 6.0.1 + ESP-SR 2.6.2, ESP32-S3 1187 Ninja steps PASS.
Official English wake name: Sophia (model ID wn10_sophia), not
Monika. Russian pronunciation «София» has NOT been tested.

Original app: 584704 bytes, SHA256
037ee3d0a333edb124d94b39de1708c6f10822bedff10c08e80a2330fb93661a.
Packed model: 383508 bytes, SHA256
f3aaf5c6017dc7460e8acd58e2204b85692747b9b5d42e6a54ee831d9fdad415.
Private only: /root/gobot-sophia-private-20261117/
Does NOT work with current RC1 layout in its default model-partition mode.

## NEW verified no-model-partition compile using app-embedded Sophia

The exact ESP-SR 2.6.2 model_path.c exposes srmodel_load(const void*).
The normal esp_srmodel_init(partition) internally mmaps the partition
and also calls srmodel_load(root). This standalone model initializer
loads the same official packed model image from a static CMake EMBED_FILES
section inside the APP, NOT an additional model data partition.

COMPILATION PASS: pinned espressif/idf:v6.0.1, ESP-SR 2.6.2,
ESP32-S3 target, all 1189/1189 Ninja steps completed.
App image 968768 bytes (0xEC840) with full SHA256:
c6e398378b8a2fbe6fbf2a2beac6b77caa776af1ca926c4adea57e1054f7d2f2.
The packed official Sophia model is 383508 bytes with SHA256:
f3aaf5c6017dc7460e8acd58e2204b85692747b9b5d42e6a54ee831d9fdad415.
ELF symbol start 0x3C07E00C and end 0x3C0DBA20 prove
383508 embedded bytes. Only exact wn10_sophia is accepted.
The app image is recognized as ESP32-S3 by esptool, validation
hash confirmed valid, ESP-IDF v6.0.1.

The test CSV uses RC1-r3 read-only recovered partition metadata,
including unchanged NVS, otadata, OTA0 at 0x20000/0x3F0000,
OTA1 at 0x410000/0x3F0000, assets at 0x800000/8MiB.
NO MODEL PARTITION. This independent app has 3160000 bytes free
in its 4128768-byte OTA slot. No part table was written to ESP.
The metadata-derived CSV does NOT verify unknown device flags.
The test image is private on Linux builder; NOT in GitHub.

IDF STATIC link memory numbers for only this standalone app:
Flash Data 470008 B, Flash Code 415070 B, DIRAM 85249 B.
These are NOT runtime memory. Model init-time, heap/PSRAM consumed
on a real ESP32-S3, CPU and coexistence with A's I2S/AEC/Opus/UI
are NOT_MEASURED. Prior RC1-r3 app was 3047680 bytes in an OTA
slot of 4128768 bytes. Whether COMBINED RC1-r3 + ESP-SR + embedded
Sophia fits and performs is NOT_PROVEN. App-only flashing
compatibility must therefore NOT be asserted.

## Prepared callable live PCM bridge

Main engine in main/embedded_sophia_engine.hpp exports
ingest_existing_pcm(epoch,sample_start,pcm,samples,recv_device_us,
on_wake,context). The SAME existing A I2S/ES8311 audio producer
should copy its mono PCM16 16kHz frames into a bounded existing
worker queue; WakeNet processing must NOT run in the I2S ISR or
interrupt Opus capture. No new I2S reader is created here.

The adapter rechunks the current 960-sample A frames into
the actual model native length, rejects sequence gaps and stale
epochs, and emits one WakeEvidence event when official
WakeNet10 detects. An idle-only gate prevents double wake and
mode switches while speaking, muted, stopping, or with a
pending turn. The callback logs sample index, device-local
monotonic detection time, processing duration, epoch/generation;
it does not save audio or transcripts. Different clocks between
device and PLAN cannot be directly subtracted.

Native C++17 PCM/gate test PASS. Static source/model/hash/no-flash
checks PASS. No actual Spotpear audio has been connected to this
interface. Standalone app_main feeds ONLY 100 SYNTHETIC ZERO PCM
frames, and never reports those as human trials or wakes.

An authenticated gobot_host_local_wake event is needed in
the HOST-A owned transport. HOST-A must preserve its 2s pre-roll,
STOP/touch/mute/Opus/UI and sole Brain activation. Never spoof
a touch wake event or change production financial settings.

## Physical test and permission gates

PLAN was OFFLINE in Remote Desktop Commander on 2026-11-17.
The Linux builder is ONLINE. No physical Spotpear, COM3 or current
unpublished HOST-A source is accessible here. The installed
RC1-r3 does NOT currently implement the Sophia engine.

Before live testing, HOST-A must:
1. Restore PLAN, complete the active hardware session and get
   exclusive Spotpear control; verify current firmware/OTA/NVS/assets.
2. Integrate source into latest real RC1-r3 (not old published commit
   a31674e), retaining one I2S/Opus audio producer.
3. Build complete integrated RC1+Sophia, check OTA size, PSRAM/CPU,
   streaming backlog/Opus drops, wake owner and same question pre-roll.
4. Prepare a verifiable app-only rollback/full snapshot path and
   obtain separate explicit Owner authorization for any actual flash.
   Do not repartition NVS/otadata/OTA/assets or use an unverified
   partition image. If a gate fails, abort the installation.
5. Once explicitly authorized, test 10+ separate Russian «София»
   and English “Sophia” voice attempts (isolated and immediate
   question), distances, near negatives «Моника», TV and genuine
   background; 30min or more to evaluate FP frequency.
   Record numeric counters/device monotonic event timestamps only.
   True acoustic name-end-to-ACK requires annotated human evidence,
   not just the model processing time.

## Status

MODEL_AVAILABLE_SOPHIA=YES
SOURCE_IMPLEMENTED_STANDALONE_AND_PCM_ADAPTER=YES
BUILT_MODEL_PARTITION_DEMO=YES
BUILT_APP_EMBED_NO_MODEL_PARTITION=YES
BUILT_COMBINED_HOST_A_RC1_APP=NO
FREE_TESTED_BUILD_NATIVE_LINK_SIZE=PASS
REAL_PCM_CONNECTED_TO_SPOTPEAR=NO
FLASH_SAFE_EXISTING_RC1_APP_ONLY=NOT_PROVEN
INSTALLED=NO
HUMAN_ACCEPTED_RUSSIAN_SOFIA=NOT_MEASURED
HUMAN_ACCEPTED_ENGLISH_SOPHIA=NOT_MEASURED
BOARD_RUNTIME_RAM_PSRAM_CPU=NOT_MEASURED
H0_HOST_A_GATEWAY_COM3_TOUCHED=NO
PAID_CALLS=0

Code only may be published to B-owned draft PR #12. The private
app binary and official Sophia model weights must not be committed.