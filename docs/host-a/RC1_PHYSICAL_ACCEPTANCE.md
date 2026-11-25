# HOST-A RC1 — physical acceptance procedure

Target: one existing Spotpear ESP32-S3 (COM3), app
`0.4.13-dev-host-a-rc1-r3`, SHA256
`5186b41a80d3f4155dd544fa1112975eca74fa4b979d62c275b6804626d13576`.

## Existing evidence (independently verifiable)

- **Full firmware app built and installed once**; no second flash allowed by
  Owner Direct #6929537812.
- 16 MiB pre/post readback preserved privately on PLAN. Bootloader, OTA
  metadata, OTA1, PHY and assets match. **NVS changed** in sectors
  `0xA000`, `0xB000`, `0xC000`; cannot assert bitwise unchanged even
  though no NVS flash write command was used and enrollment survives.
- 5-minute physical uplink: 5000 decoded Opus frames = 4,800,000 PCM samples;
  no sequence gaps; P50 packet queue age 0.0448 ms, P95 0.9349 ms;
  queue max 3 frames; 34 clipped samples, all early; no room audio saved;
  user in that session did not speak on demand.
- Actual PLAN Piper ru_RU `irina` voice was sent to physical Spotpear:
  37 x 24kHz Opus output frames, device driver started/drained ACKs.
  **This is not a person's acoustic hearing assessment.**
- Physical touch time-command window (120 seconds): **0 touch activations**.
  Returned to LOCAL after normal test timeout; not a human failure, simply
  no witnessed physical touch.
- Separate offline Piper → Whisper Small → deterministic clock → Piper test,
  on synthetic device with real offline ASR and TTS: PASS. Still
  **not a human-made question spoken to the physical Spotpear**.

## Owner-assisted human acceptance (free-only)

**One-click PLAN launcher:** open `START_HOST_A_TOUCH_TEST.cmd` from
`C:\Users\PLAN\gobot\GoBotHome-host-A` on PLAN. This is a *finite*
local console, not a scheduler/service. It requires typing `ДА` while
physically next to Spotpear, opens only isolated port 18799, then runs a
bounded USB touch trial. The separate private numeric-only report stays
in ignored `run/host-a/`. Respond to the final real-hearing/screen
questions only after actually observing the device. If no one is there,
do not start it. The default Python launcher without `--run` performs
only a file/USB-presence dry preflight and starts no listener.

**Prerequisite:** Confirm you are next to the actual Spotpear. The owner
decides when to start the test and can stop at any time. Never collect
personal speech without permission, and never save room recordings by default.

1. With the device idle, visually check that the screen is alive and that
   the face and Russian HOST/LOCAL state are displayed, not frozen.
2. Start the isolated, short-lived HOST test listener on PLAN port 18799
   using the existing `tools/host_rc1_test_listener.py`. It reads the
   existing enrolled device identity and TLS certificates from the private
   PLAN directory, but does not call Brain or paid providers.
3. Open PLAN COM3 with a bounded `tools/host_rc1_usb_free_smoke.py` session.
   It verifies actual firmware version, Wi-Fi, enrollment and idle state,
   then sends **volatile** `GOBOT_HOST_ON`. Normal default is LOCAL,
   persistent NVS enrollment must remain unchanged.
4. Tap the **physical** display briefly and say a normal, non-private,
   short Russian question: "Скажи, сколько сейчас времени?"
   For local command testing use `--local-time` on the isolated listener.
   **Do not claim a wake word** — HOST-B acoustic acceptance is pending.
5. Confirm physical screen transitions `listening → thinking → speaking`;
   server must show exactly one `manual_touch_activations` event,
   `local_command_jobs=1`, `local_command_recognized=1`.
   Actual model CPU/Opus timings and missing turns must be counted.
6. Listen to the spoken response from the device, report whether it is
   clearly audible, no pops/cutoffs, reasonable volume, correct local time.
   Device audio driver's `playing_started/drained` ACK is **not proof**
   that a person actually heard it.
7. During playback say a short test phrase; check duplex mic stream and
   echo behavior. The normal sound must not create an unapproved new turn.
   Long press physically to STOP; check cancellation, output epoch change
   and `stopped` ACK. Stale packets must not restart playback.
8. End with `GOBOT_HOST_OFF`; verify on USB
   `GOBOT_HOST_MODE OFF` and `GOBOT_STATUS ... phase=0 upload=0`.
   Do not touch the installed app, bootloader, NVS, OTA1 or production gateway.
9. After acceptance, owner reports what actually happened. Log outcomes
   explicitly for microphone, speaker, physical touch, display, STOP,
   room echo and whether a meaningful answer was understood.

**Current limitation:** RC1 firmware closes the test WebSocket without
a clean application goodbye on HOST_OFF. The server now classifies it as
`device_websocket_closed_without_host_goodbye`. This needs a future
source revision and separate flash approval; do not silently reflash RC1.

## Explicit no-go conditions

- Any B/C/OpenAI/paid or CLI model session / budget grant: **forbidden**.
- Reflashing/replacing the pinned installed r3 image: **not approved**.
- Upload or publication of device NVS, private models, credentials,
  enrollment, microphone PCM or room recordings: **forbidden**.
- Fake wake or claiming an unaccepted model recognized `Гоп`: **forbidden**.
- If an on-device test fails, record actual status rather than making up
  timestamps, hearing results, network performance or acceptance.
