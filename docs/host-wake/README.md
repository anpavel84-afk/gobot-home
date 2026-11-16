# Issue #4 — LOCAL frozen / HOST implementation checkpoint

2026-11-16. Execution report, NOT installed-product acceptance.
Owner: https://github.com/anpavel84-afk/gobot-home/issues/4

| Stage | Status | Evidence / gap |
|---|---|---|
| H0 preservation | COMPLETE | Actual source/WIP, binary, matching firmware build inputs and live Brain source/config preserved privately on PLAN |
| H1 server transport | SOURCE_IMPLEMENTED / FREE_TESTED | Real Opus, bounded queues, epochs; firmware HOST client not yet implemented |
| H2 ready Russian detector | BLOCKED_OOV | Vosk small-ru-0.22 lacks `гобот` and `габот`; `гоп` exists |
| H3 activation/Stop/feedback | SOURCE_IMPLEMENTED / FREE_TESTED, partial | Real loopback WebSocket, fake detector/client; physical feedback and full Brain handover NOT_RUN |
| Firmware candidate | NOT_BUILT | No complete device port claimed |
| Deployment / installation | NOT_PERFORMED | Installed0.4.12 and Brain9c317bc untouched |
| Human wake / physical latency | NOT_RUN | No new recording or household-audio inference |

## H0 — preserve actual LOCAL, never reset to a31674e

Original PLAN checkout: `codex/hybrid-web-vnext`, HEAD
`8586c069ccc4c1887276357099625a257b199cc8`.
Existing dirty `AGENTS.md` and `firmware/spotpear/microwake/record_raw_usb.py`
were captured with an alternate Git index; original checkout/index stayed unchanged.
LOCAL checkpoint: **`bf8a2e98cc9bd00942b1e79ac0023cd90cb9a3c8`**,
branch `archive/local-wake-20261116-bf8a2e98`.
HOST separate worktree/branch `feat/host-wake-streaming` starts from this checkpoint.
Public review is a sanitized source projection, not a push of private PLAN history.

Private recovery directory relative to original project:
`run/host-wake/h0/20261116T183634Z/` (DO NOT PUBLISH).
23 hashed artifacts: source-local.zip, local-wip.patch, source-brain-runtime.zip,
firmware-0.4.12.bin, firmware-build-inputs.tar.gz, dependency freeze, private
configurations and recovery-manifest.json. No household audio, transcript,
personal weights/features or temporary private inference diagnostics included.
No financial ledger restoration is part of rollback; rollback not physically tried.

App: **0.4.12-dev-guided-calibration-1**,3037584 bytes,
SHA256 `1acb944df377c6da4ac53b013997d9ac548e01cba6bdadece4267f7c502c5c6a`.
Stored binary matches guarded installation manifest. Fresh read-only USB confirms
version, WiFi/enrolled1, phase0, upload0, raw state0/samples0. No new flash readback.
Live Brain source archived: `9c317bca47b78f91854cd0a209a446bf574ca53b`.
Gateway remains realtime_b; B exhausted and C uncertainty unchanged.
No active personal-adaptation/recorder process found; no unrelated process stopped.

Matching build inputs copied from existing build host to PLAN: main,
managed_components, sdkconfig, dependencies.lock, partitions/licenses.
Archive SHA256 `93ea41f1e87f125461cc706335589f734f00ce1a4b778b6b9d893535c49971db`.
Upstream `a73e9a7e266e3196d1368ba46c30bee0d81f0a64`; IDF image
`espressif/idf@sha256:efc19fae2f52fc6873630c668da26aa834139a063b5fb73a46ebc0dbd217b587`.
Correct binary is build-status/xiaozhi.bin, not stale build/xiaozhi.bin.
Public model prefix SHA and zero padding verified; no private weights included.

HA/Assist/ESPHome: no matching process, Brain-environment package, usual local
config or related build-host container/service found in inspected scopes.
USED_IN_AUDIO_PATH=false: actual path is GoBot gateway -> loopback Brain.
This is not an exhaustive whole-machine installation audit. HA is a reference,
not a deployed dependency. No second Brain, supervisor or persistent listener added.

## LOCAL REJECTED / FROZEN

The local-wake experiment is rejected, not the firmware's loading/numeric parity.
Prior personal candidate was deleted and not restored. Reported8/8 isolated-name
windows include training cases: NOT independent8/8 acceptance. Slit question
windows0/2 and synthetic false events53/198,69/198 are retained as historical
numeric evidence, not household false-wakes/hour. No more calibration, corpus
synthesis, personal adaptation or threshold sweep. Existing raw expiry unchanged.

## Implemented source

- `host_wake_core.py`: RAM preroll2s/64000bytes; prefix and live join once;
  epoch/sequence validation; touch/wake single activation; finite utterance cap;
  zeroization; Stop/output epoch and acknowledgment state.
- `host_stream.py`: stateful PyAV decoder/resampler, unchanged raw Opus16k/60ms;
  separate JSON positions; queue4frames and250ms age cap; input liveness deadline;
  reconnect reset; local detector sees original PCM before conversation gates.
- `gobot_device_gateway.py`: HOST opt-in after existing auth/busy checks, before
  B/C budget. Requires explicit LAN consent and acceptance-only policy. Old paths
  unchanged by default. No provider creation/reservation in free acknowledgment.
- `host_vosk.py`: explicit local model, mandatory vocabulary check, exact stable
  first-token partial candidate matcher; no fuzzy aliases or forced grammar.
- `tools/host_vosk_smoke.py`: bounded explicit public model setup, no runtime download.

Free path emits `gobot_host_event` + existing `gobot.ui` status card and local-cue
request; NOT a fabricated Brain answer. Receipt IDs/epochs prevent stale ACKs.
Full device cue/drain handlers, physical cancellation, continuous producer counters,
firmware client, launcher switch and actual Brain conversation handover remain gaps.
Finished free-test input is cleared, not submitted to paid providers.
Host send-to-receipt times are NOT physical keyword-end-to-screen latency.
No new ambient audio/transcript persistence or cloud standby processing.

## Actual Vosk smoke / next alternative

Isolated Vosk0.3.45, model `vosk-model-small-ru-0.22` (official Apache2.0 catalog).
Archive SHA256 `961d5ff98a17f4aa6de69864d0aa71fa5bac682301d2b5d17a3f24c5c99a46d4`.
`vosk_model_find_word`: гобот=-1, габот=-1, гоп=245961.
No grammar injected. Required vocabulary gate blocks this candidate.
Model load802.15ms;30s silence computed in1.12s. These are setup/compute
observations, not speech/wake latency. Phrase/TV/human tests BLOCKED_OOV.

Official small-model compile package downloaded and inspected, not executed:
https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22-compile.zip
SHA256 `1da19d530a42dd72c93f13d07b91a0e843cb5b5f17769b3a80b556b275b04822`;
195426001 compressed /623860745 expanded bytes. Source dictionary, existing
acoustic model, Russian G2P and compile-graph.sh present. Reviewed pronunciation
addition + graph compilation is different from acoustic neural-network training.
The script also mixes an LM; do not execute its cleanup/build steps blindly.
Required Kaldi/OpenFST/SRILM tools/container not found on checked build host.
CUSTOM_GRAPH NOT_BUILT. This is a verified next path, not proof of good wake.
Alternative: ready Russian open-vocabulary streaming engine. Never substitute
робот/работ or force a sole hypothesis, and do not request another50s recording.

## Free evidence

55 new HOST tests; combined existing gateway/half-duplex/session-ACK/fast-setup/
board-B suite: **95 passed in10.52s**, JUnit `run/host-regression.xml`.
Actual authenticated loopback WebSocket + actual Opus with a fake detector;
paid client boundaries forbidden. This proves software integration only.
Accelerated30,000-frame run:1800audio seconds in2.274wall seconds, retained64000bytes.
NOT the required30minute real-time WiFi soak. No physical P50/P95 measured.

No paid calls, flash, active runtime restart, quota reset or personal training.
No continuing unattended job is left by this checkpoint. Deployment/flash still
requires separate approval after a usable detector and reviewed firmware build.

## Sources / attribution

Original GoBot implementation, not copied ESPHome I2S/firmware.
Architectural references and ready-engine APIs:
- https://esphome.io/components/voice_assistant/
- https://www.home-assistant.io/voice_control/about_wake_word
- https://alphacephei.com/vosk/models
- https://alphacephei.com/vosk/adaptation
- https://alphacephei.com/vosk/lm
- https://github.com/alphacep/vosk-api/blob/master/python/vosk/__init__.py
- https://github.com/alphacep/vosk-api/issues/2065 (third-party compile-package
  discovery; package existence/content independently checked).
