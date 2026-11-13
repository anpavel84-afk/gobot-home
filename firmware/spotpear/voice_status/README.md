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
