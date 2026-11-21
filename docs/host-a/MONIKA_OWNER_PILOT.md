# HOST-A physical Monika pilot — Owner Direct 2026-11-16

This supersedes the earlier requirement for a separate PC microphone/Monika
acoustic trial **for this experimental physical pilot only**. No claim of
human acoustic accuracy or production readiness is made.

## Integration
- Existing installed Spotpear app stays `0.4.13-dev-host-a-rc1-r3`.
  No additional flash, bootloader/NVS/partition/assets operation or H0 redo.
- Existing HOST-B `make_monika_factory` from PR #9, current read-only PLAN
  commit `758107d0a6201004554ce765076307441984e530`.
- Vosk `vosk-model-small-ru-0.22`, exact phrase_id `monika`, exact Russian
  token `моника`. No new aliases, grammar, corpora, training or computer mic.
- Only namespaced HOST-B detector package is imported. Its parent path is
  appended so B's old host_stream.py cannot shadow A's current transport.
- A keeps the canonical AudioChunk/WakeEvent, pre-roll and activation owner.
  Two seconds of RAM pre-roll join live audio without dropping question onset.
  Duplicate partials do not create a second turn. Busy playback/processing
  suppresses reactivation without changing B's recognizer.
- Wake feedback is sent on acceptance of WakeEvent, before complete-question
  ASR. Installed r3 renders Listening and supplies its own cue/refresh ACKs.
- r3 does not initialize its touch-start timestamp for a remote wake: A must
  ignore an early device finish for host_wake and finish on the existing
  detector's speech endpoint, with a ten-second capture safety cap.
- Existing free OfflineTimeResponder (Whisper Small CPU → deterministic local
  clock → existing Russian Piper voice) answers time questions. This is not
  a second Brain or paid chat. Spoken input/transcript stay in RAM only.
- Repeated local responses use fresh playback IDs and generation checks;
  manual Stop invalidates pending output. Voice stop `Гоп` is not enabled.

## Running instance and shutdown
`tools/host_monika_live.py --owner-direct-monika --seconds 7200` owns one
isolated TLS listener on existing test port 18799 and COM3. It issues the
normal volatile GOBOT_HOST_ON command, verifies r3/Wi-Fi/enrollment, and
records only numeric status in ignored `run/host-a/monika-live/status.json`.

`STOP_MONIKA.cmd` writes a shutdown request. The same serial owner retries
GOBOT_HOST_OFF until the audio driver is idle, then closes the test listener
and releases COM3. It never kills production Brain/gateway processes. The
pilot also expires after two hours; it is not an installed permanent service.

## Evidence and boundaries
- Ordinary compatibility tests only: existing selected tests 73 PASS;
  Monika protocol/multi-turn plus contract/local-command tests 39 PASS.
  The injected events in tests are explicitly non-acoustic fixtures.
- Physical startup: device UART HOST_READY; one authenticated WSS connection;
  actual Spotpear PCM processed by B's detector. No wake event was fabricated.
- SOURCE_IMPLEMENTED: integration and repeatable response path.
- FREE_TESTED: code/contract and real transport; no new acoustic acceptance.
- BUILT / INSTALLED: firmware r3 unchanged; isolated server pilot running.
- HUMAN_ACCEPTED: NOT_MEASURED. The Owner tests by ordinary spoken questions.
- Paid calls, production config changes, new flash writes, stored room audio
  and stored transcripts: zero in this pilot.

Earlier 30-minute hardware soak completed with 1800.11 s, no reconnects, and
returned to LOCAL before this pilot. Its numeric evidence remains private;
it is not evidence that Monika's acoustic accuracy has been accepted.
