# HOST-B: Sophia ESP32-S3 experimental model embedded in APP

**LATEST PHYSICAL INSTALL (2026-11-17): SOPHIA V3 INSTALLED.**
After Owner authorization, the full RC1-r3-derived Sophia V3 app
(`0.4.13-dev-host-b-sophia-active-v3`, **3,668,224 bytes**, SHA-256
`0d7bd0f65ff4a649eff16660f8bd1ee441a16314ca5bb4ecf7135e0dbd22fadd`)
was APP-ONLY flashed into existing OTA0 at 0x20000 and verified
by an independent ROM digest comparison. The physical board booted
successfully, Wi-Fi and enrollment survived, and table/OTA metadata
readbacks before and after matched byte-for-byte.

V3 now **automatically loads WakeNet10 on boot** and routes a genuine
Sophia detection into the existing GoBot wake/Brain conversation handler,
with 2s PCM pre-roll, Mute/Stop/Host fallback and bounded 3s debounce.
On-device auto-init was observed (~225ms), but **no user-confirmed spoken
Russian or English Sophia detection has yet been captured** in the
bounded live trial. An absence of wake events without spoken ground
truth does not prove acoustic failure/success.
The official model is English `wn10_sophia`, not Russian-customized
weights.

[Full V3 technical install + server report](HARDWARE_SOPHIA_V3_2026-11-17.md).
[Reproducible source-only V2→V3 patch](integration/sophia_v3_active_wake_SOURCE_ONLY.patch).
The preceding [V2 diagnostic install report](HARDWARE_INSTALL_2026-11-17.md)
is retained only as historical information, NOT current firmware state.

Earlier sections below describe historical standalone research
and MUST NOT be mistaken for the updated device-install status.

OWNER DIRECT Issue #6, draft PR #12. The official Espressif ESP-SR 2.6.2
wn10_sophia is an ENGLISH Sophia wake word, not Monika.
Russian "София" recall is still UNKNOWN: real mic is now connected and
one model event was observed, but verified spoken positive trial count
and real false-wake denominator were not established.

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
against current physical hardware in that EARLIER stage. PLAN returned
online later; the actual table and OTA metadata were verified from
physical Flash before/after the authorized app-only installation.
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

## PLAN online: read-only model and recovery checkpoint

On 2026-11-17 PLAN returned ONLINE. HOST-B independently checked that the
last HOST-A pilot was stopped and its status reported LOCAL restored;
there was no active matching HOST-A listener on port 18799. COM3 is
enumerated, but HOST-B did NOT open it. Actual live board phase was
NOT queried.

The official wn10_sophia packed image is now verified privately on PLAN
under HOST-B-lab/sophia-wakenet10-private. The new script
plan_readonly_preflight.py checks the full SHA256 of that model, the
existing installed r3 app binary and both H0/postflash 16MiB snapshot
files from the documented HOST-A run folder, **without writing anything**.
The full H0/postflash hashes match the existing HOST-A manifest and
their partition tables are identical. Crucially the historical NVS
change remains an explicit unresolved caveat. A separate historical
preflash-current.bin with a different hash is NOT treated as the
verified H0 backup.

Local checkpoint: READ_ONLY_BACKUP_AND_SOPHIA_MODEL_CHECK_PASS.
This is NOT a device check, app integration test, approval or safe-flash
verdict. HOST-A must still build and qualify an actual combined RC1-r3
app; HOST-B must not open COM3 or flash the installed board.

## RC1-r3 with real microphone diagnostic — Owner authorized trial

As of 2026-11-17, a separate full RC1-r3-derived application now compiles
with official Sophia embedded in app Flash and an actual PCM tap from the
existing LOCAL AudioService input task. Test is gated by VOLATILE UART
GOBOT_SOPHIA_TEST_ON / GOBOT_SOPHIA_TEST_OFF, no new I2S reader or cloud.
The v2 diagnostic was rebuilt to correct duplicate-wake cooldown and add
RAM/PSRAM initialization measurements. **It has NOT been flashed or run on
the physical Spotpear.** Complete test source, verified model, original r3
app and backup are stored in private PLAN directories; only source patch,
hash and handoff docs are published here.

Final B-only v2 image: **3,667,024 B**, SHA256
53b6521146cde1f64e6499d46ba9315218eacb808d6e8ea5208c66faa8187462,
giving 461,744 bytes free in the 4,128,768-byte OTA app slot.
Owner requested a physical trial, but HOST-A remains the exclusive
COM3/physical firmware executor and must independently recheck its current
board, running image/backup, full integration and safe rollback before any
single app-only write. See
[integration/HOST_A_SOPHIA_DIAGNOSTIC_HANDOFF.md](integration/HOST_A_SOPHIA_DIAGNOSTIC_HANDOFF.md)
and [integration/sophia_rc1_diagnostic_SOURCE_ONLY.patch](integration/sophia_rc1_diagnostic_SOURCE_ONLY.patch).
This test does not establish actual model RAM/PSRAM/CPU or acoustic
recognition of Russian "Со́фия" (official wake name is English Sophia).

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