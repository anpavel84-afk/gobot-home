# HOST-A HANDOFF · Sophia on the real Spotpear · NOT INSTALLED

Owner authorization: 17 Nov 2026, request to upload and test Sophia.
HOST-A is the sole operator of physical ESP32, COM3, firmware, Brain and
production/Browser Voice Lab. HOST-B supplies isolated research and reviewable
diagnostic sources. No HOST-A WIP has been modified.

## Verified full RC1-r3-derived diagnostic build

The test source is a PRIVATE COPY of the actual RC1-r3 code (never the old
published a31674e) under the isolated Linux HOST-B stage. Upgrade of ESP-SR
from the RC1-r3 baseline 2.4.7 to 2.6.2 was limited to that copy.
WakeNet10 official model wn10_sophia is embedded in APP Flash by CMake
EMBED_FILES. No model partition, bootloader, OTA/NVS or assets changes.

Compiled on ESP-IDF 6.0.1, ESP32-S3. App v2 size **3,667,024 bytes**.
Active OTA0 capacity **4,128,768** bytes: **461,744 bytes free**.
SHA256 of v2 app:
53b6521146cde1f64e6499d46ba9315218eacb808d6e8ea5208c66faa8187462

Private app on PLAN:
C:\Users\PLAN\gobot\HOST-B-lab\sophia-wakenet10-private\sophia_rc1_real_pcm_diagnostic_v2_NOT_FOR_FLASH.bin

Official Sophia model SHA256:
f3aaf5c6017dc7460e8acd58e2204b85692747b9b5d42e6a54ee831d9fdad415
Model 383,508 bytes, verified on PLAN. Model is English Sophia; actual
recognition of Russian Со́фия is NOT MEASURED.

The earlier 3,666,816-byte candidate contained a premature cooldown reset.
It was superseded by v2. Do NOT install that earlier candidate.
The v2 candidate includes corrected 3s duplicate-suppression, model
cleanup upon audio task STOP, and on-device numeric internal/PSRAM
before/after initialization measurements.

Source-only integration patch (safe to read/publish, NOT an installer):
integration/sophia_rc1_diagnostic_SOURCE_ONLY.patch
It was checked with patch --dry-run -p1 on preserved r3 source (6 files PASS).
To reproduce in an A-owned ISOLATED source copy, set the private sdkconfig
CONFIG_SR_WN_WN10_SOPHIA=y, provide the exact verified
main/sophia_srmodels.bin outside Git, and select a new unique diagnostic
version string for that test binary. Never apply this patch blindly to
HOST-A's active dirty worktree or overwrite its WIP.
Shared header / DSP sources already in this B-only folder:
main/embedded_sophia_engine.hpp, integration/sophia_pcm_tap.hpp.
The official model weights and private build endpoints are never in Git.

## Behavioral contract of the proposed diagnostic

The existing AudioService I2S/ES8311 reader remains the only microphone
producer. The local-scan 160-sample, 16kHz mono PCM16 frames feed the
real WakeNet10 DET_MODE_90 inference directly. No second I2S-reader,
Opus producer, AEC or cloud STT is created.

The diagnostic defaults OFF after every reboot and only accepts
GOBOT_SOPHIA_TEST_ON when LOCAL, idle, unmuted, no active turn, raw wake
or playback. It emits numeric SOPHIA_DIAG_ON / SOPHIA_DIAG_MEMORY and
SOPHIA_LOCAL_DETECTED (epoch, end_sample, infer_us, device timestamp).
No room audio, transcript, cloud, Brain response or personal data is logged.
GOBOT_SOPHIA_TEST_OFF restores normal LOCAL GoBot wake detection.
HOST ON is forbidden while Sophia test is enabled. Wake latching
suppresses repeats for a minimum 3-second window.

This B candidate runs DSP inference on the same local audio task, not a
bounded separate worker. Compiler PASS is not real-time CPU/Opus coexistence
acceptance. HOST-A must check scheduling and move the DSP to a bounded worker
if physical tests show unacceptable capture delays.

## STRICT gates before HOST-A performs ONE approved app-only installation

1. HOST-A confirms exclusive ownership of COM3 and that all other physical
   test workers are stopped. The current A worktree has unrelated WIP:
   do not modify/rebase/overwrite it. Integrate in an A-owned isolated
   review/candidate copy, re-run original and new regressions.
2. HOST-A verifies CURRENT LIVE device revision, ESP32-S3 rev, current app
   version and hash. Do not trust historical reports alone.
3. HOST-A checks historical full 16MB H0 backup:
   GoBotHome-host-A/run/host-a/rc1-full-readback-20261116.bin
   SHA256 c7848a7f183fc27340e7872ff8e424fa135eb8a95862a43f5996dd3d4529269b
   and postflash full readback:
   GoBotHome-host-A/run/host-a/rc1-postflash-full-readback.bin
   SHA256 98bcfdff4c9fa1e4092966336e246695a5112a17aa95c206dbfbf9eec3d31486.
   Another file named preflash-current.bin does NOT match the certified H0.
   Historical NVS sector changes are known. WiFi enrollment survived but
   do not promise bitwise NVS preservation.
4. HOST-A verifies the actual installed r3 application binary before any
   write (3,047,680 bytes SHA256
   5186b41a80d3f4155dd544fa1112975eca74fa4b979d62c275b6804626d13576).
   Active OTA0 is at 0x20000 and is 0x3f0000 bytes. Check OTA metadata
   and full rollback image before making changes.
5. NEVER run a normal full idf.py flash; that normally writes bootloader,
   partition table, OTA data and assets. A supervised application-only
   write may target ONLY active app region (0x20000) after its separate
   sanity checks, with device digest verification and postflash boot.
   If any check fails, STOP and do not flash.
6. A evaluates runtime internal/PSRAM/heap and initialization/inference
   time, screen/UI, touch, mute, STOP, Wi-Fi, AEC, Opus and old LOCAL KWS.
   The ESP-SR 2.4.7 -> 2.6.2 change could cause runtime incompatibility.
   The isolated compile is not a physical execution or an acceptance.

No HOST-B tool has opened COM3 or flashed anything; physical installation
must be done by HOST-A in its own authorized hardware session.

## First real on-device test, ONLY after A safely installs and validates

- Stay physically next to Spotpear; confirm screen and boot state.
- Send GOBOT_SOPHIA_TEST_ON in a single A-owned UART session.
- Require SOPHIA_DIAG_ON and numeric SOPHIA_DIAG_MEMORY.
- Speak Russian Со́фия 10 or more times and English Sophia 10 or more
  times in separate groups, standalone and with immediate questions.
  Count actual wake events, misses, and device-local inference times.
- Try negatives Monika, Monya, monitor, TV/background and conversation,
  plus at least 30 min background to evaluate genuine false events/hour.
- Never save microphone waveforms/transcripts, and do not use paid models.
- Send GOBOT_SOPHIA_TEST_OFF; confirm normal LOCAL old wake, UI/touch/
  mute/STOP/Opus functions. Return to LOCAL before leaving the board.
- If any boot/fallback failure, HOST-A owns app-only rollback to the verified
  r3 baseline; no NVS/bootloader/partition writes or blind retries.

## Current exact status

MODEL_AVAILABLE_SOPHIA = YES
SOURCE_IMPLEMENTED_REAL_PCM_DIAGNOSTIC = YES (isolated B copy)
BUILT_FULL_RC1_DERIVED_DIAGNOSTIC = YES (v2, ESP32-S3)
FREE_TESTED = compile, SHA, static checks and source patch dry-run PASS
FULL_RUNTIME_RAM_PSRAM_CPU = NOT MEASURED
INSTALLED_ON_SPOTPEAR = NO
HUMAN_ACCEPTED_RUSSIAN_SOFIA = NO
CURRENT_PRODUCTION_GATEWAY_CHANGED = NO
PAID_CALLS = 0
