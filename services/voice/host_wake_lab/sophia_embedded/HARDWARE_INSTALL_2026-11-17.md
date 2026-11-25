# GoBot HOST-B / Sophia WakeNet10 physical install and local voice test

Date: 2026-11-17. Owner explicitly authorized the technical installation
and physical Sophia test in this chat. This is an actual completed hardware
install, superseding earlier PR #12 documentation that had INSTALLED=NO.

## Exact actual installed firmware

Firmware diagnostic identifier:
0.4.13-dev-host-b-sophia-diagnostic-NOT-FOR-FLASH

The historical NOT-FOR-FLASH suffix was compiled into the diagnostic
identifier as a safety warning before Owner approved the hardware test.
It is not the current installation status.

Full RC1-r3-derived Sophia diagnostic app:
- 3,667,024 bytes, SHA256:
  53b6521146cde1f64e6499d46ba9315218eacb808d6e8ea5208c66faa8187462
- ESP32-S3, ESP-IDF 6.0.1, ESP-SR upgraded from the RC1-r3
  baseline 2.4.7 to 2.6.2 for this independent test image.
- Official embedded WakeNet10 English model wn10_sophia, 383,508 bytes:
  SHA256 f3aaf5c6017dc7460e8acd58e2204b85692747b9b5d42e6a54ee831d9fdad415.
  Russian pronunciation Sófiya is NOT yet validated.
- Uses existing ES8311/I2S single microphone reader and real mono
  16kHz PCM16 in the LOCAL AudioInputTask. No second I2S reader.
- Private verified app/model are on PLAN in
  C:\Users\PLAN\gobot\HOST-B-lab\sophia-wakenet10-private
  and are NOT included in Git.
- Source-only patch against preserved actual RC1-r3:
  integration/sophia_rc1_diagnostic_SOURCE_ONLY.patch;
  patch --dry-run against preserved r3: PASS.
- New source read-only validation and five safety tests passed.
- Final v2 fixes a premature model latch/cooldown reset in v1, ensures
  model cleanup on AudioService stop, and instruments true on-board heap.

## Strict pre-install flash and runtime verification

Owner-authorized PLAN physical board inspection directly via COM3:
- USB VID 0x303A, PID 0x1001; ESP32-S3 chip rev v0.2, PSRAM 8MiB,
  Secure Boot disabled, Flash Encryption disabled.
- Current LIVE GoBot UART status before write: original physical version
  0.4.13-dev-host-a-rc1-r3, wifi 1, enrolled 1, muted 0, idle phase 0,
  upload 0. No other active matching COM3 owner or 18799 test listener.
- Official original RC1-r3 standalone APP byte count 3,047,680 and SHA256
  5186b41a80d3f4155dd544fa1112975eca74fa4b979d62c275b6804626d13576.
  The ACTUAL PHYSICAL flash app at offset 0x20000 was verified against
  the exact original image by esptool verify-flash (digest matched).
- Saved genuine H0 full 16 MiB readback SHA256
  c7848a7f183fc27340e7872ff8e424fa135eb8a95862a43f5996dd3d4529269b;
  saved full post-RC1 readback SHA256
  98bcfdff4c9fa1e4092966336e246695a5112a17aa95c206dbfbf9eec3d31486.
  Both remain preserved, unmodified and out of public Git.
- Current actual partition table was read from physical Flash 0x8000
  and matched postflash backup byte-for-byte. Active OTA metadata read
  from 0xD000 passed CRC, selected ota_0.
- OTA0 begins at 0x20000, length 4,128,768 bytes;
  candidate 3,667,024 bytes fits with 461,744 bytes free.
  OTA1, NVS, bootloader, PHY and original 8MiB assets unchanged
  in the partition layout. No model partition was required.
- All B-only installation guard dry-run checks passed.

## Actual one-time physical application write and independent verification

After Owner approval and successful physical preflight, one protected
attempt marker was atomically written in private PLAN B storage BEFORE
the write. esptool performed ONE write-flash command targeting only
offset 0x20000 with KEEP options for SPI speed/mode/size.
ROM response: Wrote 3667024 bytes at 0x00020000, hash verified.
A SEPARATE post-write verify-flash command returned:
Verification successful (digest matched).
No bootloader, NVS, otadata, inactive OTA, partition table, or asset
write command was run. No second image write or model repartition.
No paid services or voice sample recording.

After hard reset the physical UART returned:
version 0.4.13-dev-host-b-sophia-diagnostic-NOT-FOR-FLASH,
wifi=1, enrolled=1, muted=0, phase=0, upload=0.
The real OTA metadata and partition descriptor sectors were read
AGAIN after installation and compared to immediately-before:
both matched byte-for-byte. Historical NVS differences between older
firmware readbacks are a known issue; do not claim NVS byte-for-byte
equality at all times merely because this job did not write NVS.

## REAL ON-BOARD WakeNet10 model initialization and test

First supervised physical LOCAL smoke:
- Explicit GOBOT_SOPHIA_TEST_ON accepted, model
  wn10_sophia initialized and UART reported SOPHIA_DIAG_ON.
- Native cold create/init duration 143,782 microseconds (~144ms).
- Internal free heap 118,983 -> 109,867 bytes: model + worker delta
  9,116 bytes (~8.9KiB).
- PSRAM free 3,615,068 -> 3,234,724: delta
  380,344 bytes (~371.4KiB).
- Zero wake events during the 28-second period; it did not contain
  a verified set of spoken positive utterances.
- Explicit GOBOT_SOPHIA_TEST_OFF acknowledged:
  SOPHIA_DIAG_OFF normal_LOCAL_wake_restored=1.
  Direct board status after OFF: WiFi/enrollment/IDLE intact.

Second bounded real-microphone trial:
- Model reinitialized successfully:
  internal free 118,983 -> 109,903 bytes (delta 9,080);
  PSRAM 3,615,068 -> 3,234,704 (delta 380,364);
  cold init time 144,447 microseconds.
- Exactly ONE genuine on-device WakeNet10 inference event emitted as:
  SOPHIA_LOCAL_DETECTED epoch=2 sample_end=781824
  infer_us=3323 event_device_us=61931851
- Inference duration for that actual detected model frame:
  **3,323 microseconds**, about **3.32ms**.
- At the end GOBOT_SOPHIA_TEST_OFF acknowledged, LOCAL fallback
  successfully restored and UART status still showed WiFi/enrolled
  and idle. No hardware failure occurred during this short test.
- Since no phoneme-aligned ground-truth utterances were recorded, the
  event cannot yet be classified as a true spoken Sophia detection
  rather than a false-positive background activation. Ask Owner whether
  they pronounced Sophia in that interval and how many times.
- No raw PCM/audio, transcript, user identity, passwords or private
  hardware MAC are stored in this report. Model never sends a paid
  cloud call or Brain request in diagnostic mode.

## Known incomplete work; no inflated acceptance claim

- Physical INSTALLATION = YES, verified ROM and UART.
- Physical model RUN = YES, init and actual detection event seen.
- CPU usage for a single detected frame = 3.323ms, not an entire
  sustained utilization measurement or audio name-end wake latency.
- True Russian Sófiya sensitivity, comparison with English Sophia,
  room/TV false wake rate, true latency from end of name to cue, live
  Opus/Brain interoperability and long duration stability remain
  NOT MEASURED/NOT ACCEPTED.
- This is a VOLATILE local diagnostic: default OFF at reboot. It does not
  change the production Brain/PC voice pipeline or create a device
  assistant turn. Production always-on Sophia is NOT enabled.
- The test used a B isolated copy of original r3 and the A-provided
  guarded serial/flash environment, with direct current Owner approval.
  HOST-A active Git worktree WIP was not modified.

## Recovery

Original RC1-r3 app image, physical H0 full readback and postflash
readback remain securely stored on PLAN. Only A's controlled app-only
rollback to the verified baseline should be used if a later device
fault is encountered; no full idf.py flash, blind retries or
partition/NVS writes. The current diagnostic is functioning, so no
rollback was necessary in this session.

## Release/status flags

MODEL_AVAILABLE = YES: official wn10_sophia, not a Monika model
SOURCE_IMPLEMENTED = YES: current real ESP32-S3 LOCAL mono PCM tap
BUILT = PASS: full RC1-r3-derived app
FREE_TESTED = PASS: ROM verify, boot, model init, OFF fallback
INSTALLED = YES: verified physical ota_0 application
REAL_MODEL_EVENT = 1 during bounded live observation
HUMAN_ACCEPTED = NO: spoken positive/negative ground truth not verified
PRODUCTION_LOCAL_ALWAYS_ON = NO: diagnostic OFF
PAID_API_CALLS = 0
PERSONAL_AUDIO_SAVED = NO
GITHUB_BINARY_OR_WEIGHTS = NONE
