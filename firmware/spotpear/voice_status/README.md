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
the user saw the mode or thinking indicator. Physical installation remains gated
by the Owner's later Night Train no-flash instruction. No OTA/NVS/flash here.
