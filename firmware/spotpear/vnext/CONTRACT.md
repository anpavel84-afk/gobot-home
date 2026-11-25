# Web vNext hardware preparation

Installed firmware remains **0.4.3-dev-media-ready**. No flash, OTA, NVS write,
wake-to-Brain change or physical acceptance was performed in Night Train.

`prepare_candidate.py` applies only to a COPY of the verified media-ready source.
It advertises `gobot_contract=3`, existing `scene_contract=2`,
`playback_ack_precision=activity_only`, `segment_position=false` in
`gobot_session_ready`. The gateway must negotiate these fields and use coarse
resume at the current segment; it must not infer a sample cursor from playback
activity. Existing 0.4.3 clients omit these fields and retain legacy handling.

Browser acknowledgments identify stream, segment, client and presentation epoch,
with positions measured on the browser AudioContext clock. They are scoped
playback reports, not authorization to run tools or proof of acoustic audibility.
Hardware needs a future bounded decoded/played-sample counter before it can
advertise equivalent precision. Stop must invalidate the output epoch and drain
the local queue before listening is resumed. Reconnect never replays a paid job.

## Candidate build (not installed)

- Build host: vmi3510488; isolated copy `/opt/gobot-firmware/20261112-gobot-v1/night-train-stage-v1`.
- Base upstream: `a73e9a7e266e3196d1368ba46c30bee0d81f0a64`; custom media-ready 0.4.3 sources retained untouched.
- Version: **0.4.4-night-contract**; ESP-IDF **6.0.1**, esp-sr **2.4.7** unchanged.
- Pinned image: `espressif/idf@sha256:efc19fae2f52fc6873630c668da26aa834139a063b5fb73a46ebc0dbd217b587`.
- Network disabled; no devices mounted. `idf.py reconfigure`, then `ninja -C build -j2`.
- Artifact: `build/xiaozhi.bin`, **2711488 bytes**.
- SHA256: `fe624dc9f020c4be738d05bb458cf800dcc16990a3ee4d1e8a5a2c3282b0d141`.
- Partition checker: app `0x295fc0`, partition `0x3f0000`, 34% free.
- First compile exposed a missing include in the preparation script; corrected,
  rebuilt successfully. No runtime RAM/performance or acoustic claim follows.

This is a negotiation patch, not a complete device port of the browser narrator.
The existing renderer, Brain, A/B/C and audio paths are preserved. Physical
installation and an active-session test require a separate authorized stage.
