# GoBot Home firmware v1 — hardware-first release contract

Status (12 November 2026): **experimental 0.1.0-dev-gobot booted on Spotpear; local KWS gate failed**.
Owner direction: hands-free local wake word is mandatory; no button-only release.
Target physical hardware: Spotpear EN-V5 With-B-1, ESP32-S3 v0.2, 16 MB Flash,
8 MB PSRAM, 240x240 round display. Board profile to be hardware-smoke validated:
`main/boards/spotpear/sp-esp32-s3-1.28-box` at upstream SHA
`a73e9a7e266e3196d1368ba46c30bee0d81f0a64`.

## Architecture

- Device: local AFE/WakeNet, 24 kHz ES8311 audio I/O, Opus framing, display/LVGL,
  button as fallback, secure Wi-Fi and controlled OTA. No heavy LLM on ESP32.
- PLAN: **same** GoBot Brain for device and web; authenticating bridge from
  ESP32 WebSocket/Opus to Brain (real ASR, LLM, TTS), visual command projection.
  Existing voice_mock protocol fixtures are NOT production acceptance.
- Enrollment: owner provisioned credentials and scoped device identity; never
  commit secrets or flash dump. Avoid cloud XiaoZhi backend in product mode.

## P0 required interaction semantics

1. Boot: restore Wi-Fi, show idle/wake status, start **only local wake detector**.
   No always-on speech streaming, no unsolicited cloud speech or model requests.
2. Detect wake word locally: open authenticated GoBot audio channel, show listening.
   Use VAD/end-of-speech/timeout to close user utterance, no long hanging pauses.
3. Answer: stream Opus TTS and display compact content. Allow safe interruption.
4. End answer: **drain playback first**, then close audio channel and re-arm local
   wake detector. No transition to a new server-listening turn by default.
5. On failed connect / disconnect / watchdog: make error visible briefly, close
   stale channel, preserve OTA rollback, recover local wake mode with backoff.
6. Optional short follow-up window is DISABLED in v1; implement only with
   explicit owner approval and strict time/privacy bounds.
7. Hardware mute state is separate from wake standby; notify/firmware actions
   require independent permission. Wake packets need not contain raw wake audio.
8. No firmware image or deployment without confirmed model, factory backup,
   chip/flash size, source/version/asset provenance, rollback procedure and tests.

## Local wake words

The only activation phrase is «ГоБот». On the physical board the MultiNet7
English phonetic candidate detected 0/3 synthetic positive samples and 0/4
negatives. Initialization failed closed. No human recognition has been measured.
The trained Russian compact frontend experiment and results are in
[the hardware evidence](spotpear/acceptance.json).

## Implementation assets already present

- `firmware/gobot-one-turn.patch`: compile-time optional
  `CONFIG_GOBOT_WAKE_ONLY` changes TTS-stop processing so speaker output
  drains, channel closes, state returns to local wake standby; test candidate
  applied via `git apply --check` to pinned upstream, **not compiled**.
- `firmware/custom-ui-card.patch`: existing candidate for basic status/timer
  cards, not full visual v2 consumer, **not compiled**.
- `firmware/sdkconfig.gobot.defaults`: preexisting board/LVGL/UI settings,
  not a release configuration with validated wake model.
- `docs/HARDWARE_CHECKLIST.md`: physical board ID and full factory backup.
  Factory flash primary + second owner-private copy, 16,777,216 bytes SHA256
  `1FE1E310D86425DBE2432133C8712AECB64262BB3649647A5104989DE671F4E6`.

## Required release gates (all must pass)

- A. Build with pinned ESP-IDF/toolchain, esp-sr/selected wake model and
  board profile, reproducible hash, partition layout and signed/verified OTA.
- B. Factory rollback validated; no wipe of owner credentials/NVS by accident.
- C. Real device: wake phrase 30/30 trials at several distances and noise
  conditions; 60 min standby without unintended turns; record actual errors.
- D. Single turn without button: native C -> GoBot Brain -> speech + screen -> idle; explicit A separately.
  Test reconnect, 3 failed connects, network loss during TTS and hard mute.
- E. Ensure displayed speech/Opus frame boundaries, no audio-loop duplication,
  no hanging listening state, perceptible diagnostics on error; measure
  end-to-end speech latency and false wake rate.
- F. Confirm remote security: TLS, device identity, outbound-only audio
  connection, no public unauthenticated debug endpoints.

Sources: https://github.com/espressif/esp-sr ; https://docs.espressif.com/projects/esp-sr/en/latest/esp32s3/wake_word_engine/ESP_Wake_Words_Customization.html .
