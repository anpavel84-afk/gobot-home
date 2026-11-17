# HOST-B: Sophia ESP32-S3 experimental model embedded in APP

OWNER DIRECT Issue #6, draft PR #12. The official Espressif ESP-SR 2.6.2
wn10_sophia is an ENGLISH Sophia wake word, not Monika.
Whether Russian "София" works is UNKNOWN. No real mic test performed.

## App-embedded model and live PCM path

Unlike the previous model-partition standalone app, this independent
experiment uses srmodel_load(const void *root) from the EXACT ESP-SR
2.6.2 installed source, with a verified packed official Sophia model
EMBEDDED in app flash via CMake EMBED_FILES. The regular partition
loader internally uses the same srmodel_load entrypoint. There is no
need to move data or add a "model" partition for this isolated design.

The exact binary input file is sophia_srmodels.bin, 383508 bytes,
SHA256 f3aaf5c6017dc7460e8acd58e2204b85692747b9b5d42e6a54ee831d9fdad415.
It is PRIVATE, never committed to GitHub and not renamed Monika.
Only 1 model with its actual name wn10_sophia is accepted by this source.

The file partitions_RC1_LAYOUT_CHECK_ONLY.csv represents read-only
metadata recovered from Spotpear: NVS 16KiB, otadata 8KiB,
OTA0 and OTA1 0x3f0000 bytes each, assets 8MiB, no model partition.
It is a SIZE CHECK ONLY; its flags/assets state have NOT been verified
against current physical hardware because PLAN is offline.
DO NOT FLASH the table on the installed device.

The main/embedded_sophia_engine.hpp interface exposes the real
ingest_existing_pcm(epoch,start_sample,pcm,samples,packet_receive_us,...)
method. HOST-A can call it from a bounded audio worker using the
SAME existing ES8311/I2S capture stream that is also fed to Opus.
No second I2S reader, no new AEC, no audio persisted.
Mono signed int16 samples at 16kHz are rechunked to the true WakeNet
model native chunk length, not guessed in advance.

ExclusiveWakeGate defaults to PLAN_STREAM, switches to
ESP_LOCAL_SOPHIA only IDLE and with no outstanding turn, mute, Stop
or playback. It rejects gaps, stale generation and double wakes.
The event callback contains sample_end, packet_receive_us,
device monotonic detect_us, model_infer_us and stream epoch.
HOST-A must authenticate and validate event over existing WSS
rather than spoof a physical touch.

The standalone app_main() exercises exactly that callable PCM
interface with 100 frames of SYNTHETIC ZERO PCM, and NO I2S hardware.
No production gateway, Brain, key, budget, NVS, OTA or assets edits.

## Test and release gates

Source builder: espressif/idf:v6.0.1, ESP-SR 2.6.2, ESP32-S3.
Host-native C++ test integration/test_sophia_pcm_tap.cpp passed.
Embedded model build and artifact details are in BUILD_REPORT.md.
This is NOT a combined RC1-r3 app and cannot be flashed just because
its standalone image fits an app partition.

Before live tests: (1) PLAN online; (2) HOST-A releases its hardware
session and authorizes exclusive COM3; (3) HOST-A integrates the
tested PCM API into its CURRENT WIP RC1 source; (4) the true combined
app must build and fit unchanged OTA0 size and work with Opus/UI/PSRAM;
(5) verify original full backups/rollback and obtain Owner's separate
explicit permission before any flashing. Do not repartition assets,
NVS or bootloader. Do not activate paid Brain in the wake test.

For human tests only AFTER those gates:
- 10+ native Russian "София" utterances; 10+ English "Sophia".
- Both isolated names and name immediately followed by a question;
  distance, normal household noise, TV, near-names, including "Моника".
- Log only event counters and device monotonic timestamps.
  No raw household PCM or transcripts without additional consent.
- Distinguish per-frame model inference delay from true name-end to
  user-audible wake confirmation, which requires human-annotated onset.
- Measure actual RAM/PSRAM, CPU, Opus drop/overrun and app size with
  current RC1. Do not claim this from a compile or vendor benchmark.

Release: MODEL_AVAILABLE_SOPHIA=YES; standalone app SOURCE=YES;
REAL_PCM_CONNECTED=NO; RC1_COMBINED_APP=NOT_BUILT;
INSTALLED=NO; HUMAN_ACCEPTED=NO; paid calls=0.