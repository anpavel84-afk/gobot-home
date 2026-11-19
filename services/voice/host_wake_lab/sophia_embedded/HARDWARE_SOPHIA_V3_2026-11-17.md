# GoBot HOST-B: Sophia V3 physical installation + guarded RealTime B recovery

Date: 17 November 2026, Brazil time.
This file records ACTUAL completed operations on Spotpear ESP32-S3 and PLAN,
and keeps the distinction between **technical install** and **human acoustic
acceptance**. Owner explicitly permitted both the firmware installation and
the use of paid RealTime B / Live C models. No OpenAI spending limits were
removed and no older financial sessions were deleted.

## What was really installed

- Previous diagnostic V2, physically installed earlier:
  \`0.4.13-dev-host-b-sophia-diagnostic-NOT-FOR-FLASH\`,
  3,667,024 B, SHA256
  \`53b6521146cde1f64e6499d46ba9315218eacb808d6e8ea5208c66faa8187462\`.
  V2 required a volatile UART command to enable the engine and only
  logged WakeNet detections; it did not wake the Brain. V2's one real
  model event had no independently confirmed spoken ground truth.
- **NEW V3 physically installed and verified:**
  \`0.4.13-dev-host-b-sophia-active-v3\`, 3,668,224 B,
  SHA256 \`0d7bd0f65ff4a649eff16660f8bd1ee441a16314ca5bb4ecf7135e0dbd22fadd\`.
  Built from a separate private copy of actual RC1-r3, ESP-IDF 6.0.1,
  ESP-SR 2.6.2 with official WakeNet10 \`wn10_sophia\` model embedded in
  the APP. Model is English "Sophia" (not Russian custom weights).
- Exact private binary saved on PLAN under:
  \`C:\Users\PLAN\gobot\HOST-B-lab\sophia-wakenet10-private\sophia_rc1_always_on_v3_20261117.bin\`
  with full SHA256 verified both on Linux builder and PLAN. Neither the
  binary nor the official model weights are committed to GitHub.
- Same existing OTA0 app region at \`0x20000\` with capacity
  **4,128,768 B**, nominal margin **460,544 B**. No partition migration,
  no second I2S reader, no new NVS/mute/settings/financial writes.
- Pre-install **LIVE BOARD** read-only check verified V2 byte-for-byte
  on actual Flash using esptool verify-flash, current OTA0 selection
  with valid CRC and unchanged partition table.
- **ONE app-only write** at \`0x20000\`; ROM \`Hash of data verified\`.
  A separate ROM verify-flash returned
  \`Verification successful (digest matched)\`. The ESP rebooted and
  returned the exact V3 version, \`wifi=1 enrolled=1 muted=0 phase=0
  wake_running=1 upload=0\`.
- Post-install **physical readback** confirmed partition descriptor and
  OTA selection metadata bytes match the immediately-before-flash
  snapshots. No bootloader, otadata, inactive OTA1, NVS or assets
  write/erase commands were run.
- The preserved original RC1-r3 app, previously installed V2 app and
  full historical H0/postflash 16 MiB backup checksums remain in
  secure private directories on PLAN for an explicitly controlled
  APP-ONLY rollback if required. No rollback needed in this session.

## How V3 routes the actual wake

The previous V2 local wake event was a **diagnostic-only UART event**.
The new source-only V2→V3 patch
\`integration/sophia_v3_active_wake_SOURCE_ONLY.patch\`:
1. defaults to local Sophia ON in volatile memory on each boot,
   no NVS setting required;
2. reads **the same** ES8311/I2S 16kHz mono PCM16 that the existing
   AudioService task already captures; a second I2S reader is forbidden;
3. maintains a bounded local PSRAM question queue, including
   **2 seconds of pre-roll**, to preserve the immediate question after
   the name; native standalone WakeQuestionBuffer test PASS;
4. on an actual official WakeNet10 detection, signals the existing
   AudioService wake callback \`on_wake_word_detected("София")\` and
   the existing Application main-task wake route
   \`StartGoBotTurn("wake")\`. This preserves the existing Opus/Brain/UI
   conversation architecture rather than fake touch events;
5. enforces 3-second wake debounce, one local source, bounded queue,
   fail-closed overflow and safe switch to/from HOST mode;
6. preserves Mute, Stop, touch and the explicit
   \`GOBOT_SOPHIA_TEST_OFF/ON\` fallback switch, and does not activate
   paid sessions except as a consequence of a real GoBot voice turn.

Firmware ELF, ESP-IDF app partition size check and native/static
source tests passed. The actual V3 model initialized on the device
*without* the ON UART command, ~225ms cold create.
Measured device free memory on that trial:
internal before 127,651B / after 115,735B (**11,916B delta**),
PSRAM before 4,663,224B / after 3,977,080B (**686,144B delta**,
which includes the new local PCM queue and model allocations).

### What is NOT yet demonstrated

A live UART monitor recorded the correct installed V3 version and
\`SOPHIA_DIAG_ON model=wn10_sophia\` after cold reboot, and
\`wake_running=1\` with Wi-Fi and enrollment intact.
It observed **zero** \`SOPHIA_LOCAL_DETECTED\` /
\`SOPHIA_WAKE_DISPATCH\` / \`GOBOT_ACTIVATION source=wake\`
events in two bounded observation windows. There were **no
time-aligned, user-confirmed spoken positive trials in those windows**.
The absence of events alone does NOT establish failure or success of
the model on spoken Russian «Со́фия».

Thus: **INSTALLED=YES**, **LOCAL_MODEL_AUTOSTART=YES**,
**WAKE_TO_GOBOT_SOURCE_IMPLEMENTED=YES**, **BUILT=YES**,
**POSTFLASH_VERIFIED=YES**, but **HUMAN_ACCEPTED=NO**.
Actual wake recall for Russian «София», English "Sophia" and genuine
false-wakes/hour, as well as end-of-name-to-ACK P50/P95, remain
NOT MEASURED. The official model is trained for English Sophia.
RealTime B can respond when a real paid-authorized turn occurs; no
successful voice answer on the physical device has been verified yet.

## Server and accounting on PLAN

Earlier, touch showed «Связь прервана» because the original device
LAN WebSocket gateway \`192.168.3.15:18789\` was NOT running.
The Brain \`127.0.0.1:18781\` and LiveKit \`127.0.0.1:17880\` were
also down. Both were restarted using existing managed/service tools;
an isolated free \`hardware_test\` gateway verified TLS, hello,
actual ESP32 Opus uplink and a synthetic 5-packet Opus downlink,
and verified an on-device sound-check command.

C paid test returned an unresolved provider close; **Live C remains
blocked by \`live_previous_finalization_unconfirmed\`**.
Old C calls remain reserved and unconfirmed rather than being erased.
No automatic new C provider sessions were started after the new block.

The prior B test roots were exhausted or expired:
\`run/voice-ab-b\` had 8 total old sessions and
\`run/voice-ab-b-wake\` had three old trial sessions with expired grant.
No prior B usage table was cleared or reauthorized in-place.

With explicit user permission, a separate **NEW finite owner B trial
epoch** was created under the private runtime path
\`run/voice-ab-b-wake-renewal-20261117\`. The unchanged
\`WakeTestBudget\` enforces 3 sessions maximum, 60s each,
8 responses/session, 512 output tokens/response and a 1 USD
estimated limit; this is NOT a provider invoice/hard dollar cap.
Grant expires 2h after creation, requires the same exact enrolled
device and the same model \`gpt-realtime-2.1-mini\`, voice \`marin\`,
no automatic paid retries.

A private online SQLite backup was made of the old B wake trial ledger,
along with old mount/policy/source. Only a five-line explicit new mount
branch was added to the existing Brain source; the old mount profile
still exists and old journals stay untouched. Original gateway.json
remains the exact prior \`realtime_b\` config; no account token or
device ID is published here.

The managed GoBot Brain server was safely restarted with zero active
paid sessions; **18/18 owner/B budget regression tests passed**.
Brain status subsequently returned **RealTime B enabled=True**,
3 sessions remaining, no admission reason.
Original \`realtime_b\` TLS gateway on \`192.168.3.15:18789\` was
restarted. Its authenticated Hello/Access exchange returned
**allowed=True**, continuous=True; the no-audio acceptance test
started **zero** provider sessions.

## Current release flags

MODEL_AVAILABLE_SOPHIA = YES
INSTALLED_SOPHIA_V3 = YES
APP_ONLY_OTA_SHA256_VERIFY = PASS
POSTFLASH_PARTITION_AND_OTADATA_COMPARE = PASS
LOCAL_WAKE_ALWAYS_LISTEN_INIT = PASS
LIVE_USER_SPOKEN_SOFIA_WAKE = NOT_ACCEPTED
REALTIME_B_SERVER_LISTENING = PASS
REALTIME_B_NO_AUDIO_ADMISSION = PASS
REALTIME_B_NEW_FINITE_GRANT = 3x60s, $1 estimated, 2h, limited
LIVE_C_SERVER = blocked by older finalization debt
DEVICE_FULL_PAID_CONVERSATION = NOT_YET_VERIFIED
PRODUCTION_HARDENED = NO
PERSONAL_AUDIO_RECORDED = NO
GITHUB_MODEL_BINARIES = NONE
