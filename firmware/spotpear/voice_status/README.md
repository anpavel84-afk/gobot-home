# Device voice-state UI candidate

Apply `prepare_candidate.py` only to a COPY of installed0.4.3 media-ready source.
It adds bounded optional voice_engine(A/B/C) and voice_phase fields to the
existing session-scoped custom scene. The actual audio turn guard/playback
reports remain authoritative; a visual thinking override never changes audio.
Mode labels coexist with the timer. End clears the session's visual state.

Build with the pinned image from BUILD_MANIFEST.json, network disabled, no device
mounts. `test_ui.cc` exercises old A waiting controls and renders authored mock
fixtures; it does NOT prove physical LCD or acoustic behavior. The reviewed PNGs
under fixtures are native-renderer output, with no household content or live data.

Installed0.4.3 ignores these optional fields and its fixed face renderer hides
legacy SetStatus text. Therefore server packet delivery alone is NOT proof that
the user saw the mode or thinking indicator.

Owner explicitly approved this UI candidate on 2026-11-13, superseding the
Night Train no-flash restriction for this image only. It is now installed by USB
and verified on the enrolled Spotpear: version, Wi-Fi, enrollment, standby with
upload=0 and volume100 confirmed. App-only write at0x20000; boot/OTA metadata,
inactive slot and assets independently matched the preflash snapshot. Logical
NVS configuration was retained; ESP-IDF refreshed only phy/cal_data during boots.
Physical LCD and touch acceptance still require the Owner's observation.

Guarded rollback (idle board, fresh snapshot and identity checks):
`data/hardware/venv/Scripts/python.exe firmware/spotpear_bringup.py voice-status-rollback`.
This restores the verified0.4.3 app only, without restoring financial data or NVS.

## Touch-first capture installed (2026-11-13)

`prepare_fast_start.py` applies only to a COPY of the installed UI source.
`FAST_START_MANIFEST.json` identifies the pinned offline0.4.5 candidate. Touch
enables local audio processing before network setup; an explicit bounded7.2s
Opus queue retains the beginning until existing access/media-ready gates open.
Overflow cancels, Stop clears pending packets, ordinary streaming keeps its2.4s
queue policy. No paid standby session or second STT. Setup completion avoids
restarting capture. The120ms warmup discard is skipped only for local startup.
Owner separately approved this image and free local diagnostics. Guarded app-only
USB installation and boot/Wi-Fi/enrollment are verified. Fresh full preflash image
is private on PLAN; NVS configuration/boot/OTA metadata/inactive slot/assets match.
Three board tests with a fake local backend passed:2s delayed-ready retained the
audio prefix (70064 received samples), overflow cancelled without upload, and
network close before ready returned idle. All ended with upload0; no model calls
or saved raw audio. Gateway restored to real B, original configuration retained.
Local capture handler reported3ms in all three USB diagnostic starts. This is NOT
a measured human touch-to-first-sample result or first-syllable acoustic acceptance.
Physical hold Stop, display and real-model conversation still need Owner testing.
`fast-start-rollback` restores the verified UI-only0.4.4 app with a fresh backup
and identity checks. Do not restore financial ledgers for a firmware rollback.
