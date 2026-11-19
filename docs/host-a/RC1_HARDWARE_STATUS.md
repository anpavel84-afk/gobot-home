# HOST-A RC1 hardware release checkpoint — 2026-11-16

Owner Direct: Issue #5, comment #6929537812. This report is **not a human
acceptance** and does not authorize paid sessions or a second firmware install.

## Verified H0 / isolated source
- Main PLAN checkout retained HEAD `8586c069` with original dirty files unchanged.
- H0 `bf8a2e98`, private H0 app `0.4.12-dev-guided-calibration-1`,
  SHA256 `1acb944df377c6da4ac53b013997d9ac548e01cba6bdadece4267f7c502c5c6a`.
- Brain read-only runtime `9c317bca`; production voice B remaining sessions=0,
  production gateway `realtime_b` not switched.
- HOST-A source worktree exclusively `GoBotHome-host-A/feat/host-transport`.
  HOST-B lab and original HOST worktrees untouched.
- Original full physical 16 MiB readback private on PLAN, SHA256
  `c7848a7f183fc27340e7872ff8e424fa135eb8a95862a43f5996dd3d4529269b`.
  Its exact H0 app resides in active `ota_0`, base `0x20000`; OTA
  selection seq=1, state=VALID, CRC checked. The backup includes NVS and assets
  but must **never** be published.

## SOURCE_IMPLEMENTED
- Reproducible XiaoZhi ESP32-S3 app port over preserved 0.4.12 source,
  `firmware/spotpear/host/prepare_host_rc1.py`. Actual edits include
  `Application`, `WebsocketProtocol`, 16 kHz Opus producer sequence, 24 kHz
  inbound decoder using the **existing** audio codec, device AEC, touch
  activate/Stop, stream epochs and playback_id verification, cue and native
  LVGL refresh receipts, mute, reconnect loop, finite stream queues.
- HOST selection is volatile via `GOBOT_HOST_ON` / `GOBOT_HOST_OFF` on
  existing USB serial; normal LOCAL is the unchanged default. The test WSS
  endpoint is a **private build-only** header, not production enrollment or
  NVS. No unaccepted wake model was enabled.
- An isolated short-lived PLAN listener on port 18799 used the existing
  authenticated device identity/TLS certificate and a permanently forbidden
  paid client. No second Brain, production listener or scheduler created.
- Server-only post-test correction: normalize first Opus decoder pre-skip
  of 16 samples (1 ms) with leading zero padding to preserve exact
  `AudioChunk.sample_index = producer_seq * 960`. No firmware reflash needed.
- Numeric-only PC microphone monitoring (PCM peak, RMS, clipped-count,
  queue counters) is opt-in to the isolated test and never writes PCM/audio.

## FREE_TESTED
- Native C++ `host_rc1_state.h` test PASS: epoch, sequence, duplicate/stale
  output, STOP and reconnection reset.
- Full project selected software regression: **155 passed, 11 skipped**
  before the first physical test; after server-only Opus first-packet timing
  fix **156 passed, 11 skipped, 0 failed**. No paid external calls.
- Real hardware test #1, **63.66 audio seconds**:
  1061 valid in-order inbound Opus packets (seq 0..1060), queue max=2,
  max observed packet queue age=1.601 ms. PLAN sent 7 local fixture Opus
  packets, and the actual device returned software/driver
  `playback_started` and `playback_drained` receipts. Provider calls=0,
  raw recordings saved=FALSE. Return to volatile LOCAL acknowledged on UART.
- Real hardware test #2, **28.56 audio seconds microphone-only**:
  476 input packets, 475 decoded before deliberate close, source
  seq 0..474; peak decoded PCM amplitude 32768, 36 clipped sample values
  in 455984 actual decoded samples, all clipping accumulated during early
  startup; no additional clipping later. Min per-frame RMS about 352.
  This establishes a real signal but **does not prove speech intelligibility**.
  The first frame was 16 samples short due decoder pre-skip; fixed server-side
  after this test. No cloud or disk recording.
- Hardware test #3 after the *server-only* timing correction: 342 processed
  60 ms source Opus packets -> **exactly 328320 PCM samples = 342*960**,
  queue max=2, max queue age=1.422 ms. At the deliberate device OFF,
  343 packets had been received and the final frame had not yet been
  processed. PCM clipped sample count was **1046/328320** in this run;
  mic gain/AEC must be verified acoustically. No second flash or paid calls.
  Volatile HOST OFF returned device to LOCAL.
- Both test sessions exited to LOCAL. The server registered
  `ConnectionClosedError` at deliberate `GOBOT_HOST_OFF`: a known ungraceful
  shutdown, not proof of network disconnect immunity. Do not mark reconnect
  or clean close accepted.
- Real 30-minute Wi-Fi soak: **NOT_RUN**. Earlier 1800 accelerated synthetic
  audio seconds are NOT an actual 30-minute hardware soak.

## BUILT
- `0.4.13-dev-host-a-rc1-r3` complete ESP-IDF 6.0.1 app image.
  Pinned image `espressif/idf@sha256:efc19fae2f52fc6873630c668da26aa834139a063b5fb73a46ebc0dbd217b587`.
- Final binary: **3,047,680 bytes** SHA256
  `5186b41a80d3f4155dd544fa1112975eca74fa4b979d62c275b6804626d13576`.
  ELF SHA256 `784d59d21e619df4334835e261fba582cf0a2a23fc7f73c021dd9c05d7c798ac`.
  4,128,768-byte active app partition; approx. 26% free.
  Build manifest and executable remain private; no image committed to GitHub.

## INSTALLED
- **YES: one approved app-only flash**, active `ota_0` address `0x20000`,
  via guarded esptool command; exactly one test candidate, no retry.
- Physical ESP32-S3 rev 0.2, 16 MiB flash, 8 MiB PSRAM, COM3 verified.
  Secure Boot and flash encryption disabled.
- Exact app bytes verified on board after writing via esptool digest.
  UART boot verification: `version=0.4.13-dev-host-a-rc1-r3`,
  `wifi=1 enrolled=1 muted=0 phase=0 upload=0`. Normal LOCAL working.
- Second full 16 MiB private readback obtained, SHA256
  `98bcfdff4c9fa1e4092966336e246695a5112a17aa95c206dbfbf9eec3d31486`.
  Installed app verified against the new image. Original bootloader,
  partition table, otadata, phy_init, inactive ota_1 and assets
  verified unchanged. NVS is a separately documented exception below.
- **NVS caveat**: between two full readbacks 3 NVS sectors changed:
  `0xA000`, `0xB000`, `0xC000`. The single flash command erased/wrote
  only inside `0x20000..0x308FFF`, so no direct NVS write/erase command
  occurred. The cause/timing of NVS change is UNKNOWN; it may be ordinary
  runtime NVS activity during repeated boots. Wi-Fi and enrollment survived,
  but *bitwise NVS preservation cannot be asserted*. This is open evidence,
  not a hidden PASS.
- Preserved H0 rescue app was proven readable via ROM, and exact
  `verify-flash 0x20000 H0` succeeded before install. Recovery action,
  **only if hardware fault or new Owner direction**, is an app-only
  `esptool write-flash 0x20000 <private-preserved-H0.bin>`, followed by
  digest and boot verify. No actual rollback executed.

## Acceptance / outstanding
- HUMAN_ACCEPTED: **NO**. User has not yet confirmed intelligible live
  speech, audible output, physical touch/display, volume or acoustic onset.
- FREE_AUDIO_E2E: hardware WSS/Opus transport and firmware output receipts YES;
  subjective acoustic quality unverified.
- BRAIN_E2E: **NOT_DONE**; fixture is not a model response.
- WAKE_HUMAN: **NOT_ACCEPTED**; HOST-B independent and no fake wake.
- PAID_MODEL_E2E: **NOT_RUN**; board B budget exhausted and C unknown.
- TOUCH_STOP_PHYSICAL, WIFI_30MIN_SOAK, AEC_ACOUSTIC, P50/P95 of first
  meaningful reply: **NOT_MEASURED**.
- Device left in LOCAL. No paid B/C/CLI calls, NVS erasure command, production
  gateway switch, master merge, or second firmware flash.

This report records only the measured gates and explicitly names the gaps.
