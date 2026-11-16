# GoBot HOST-A (Issue #5) — local PLAN execution, 2026-11-16

This is a source/free-test report. It does NOT authorize an installation.

## Verified starting point
- Main PLAN root branch `codex/hybrid-web-vnext` HEAD `8586c069`, original dirty AGENTS.md and record_raw_usb.py unchanged.
- H0 commit `bf8a2e98` exists. Archived app 0.4.12 SHA256 `1acb944df377c6da4ac53b013997d9ac548e01cba6bdadece4267f7c502c5c6a`.
- H0 build-input archive SHA256 `93ea41f1e87f125461cc706335589f734f00ce1a4b778b6b9d893535c49971db`.
- The running Brain reported `9c317bca`; its current active_turns and active_voice_streams both 0. Live gateway mode `realtime_b`, continuous_live=true, host_wake.enabled=false, latency_enabled=false. B: 0 remaining sessions, enabled=false.
- HOST-A exclusive worktree `C:\Users\PLAN\gobot\GoBotHome-host-A` branch `feat/host-transport`, based on prior HOST `64ba27e`. Existing original HOST and HOST-B detector worktrees left untouched. Read-only service audit is **ignored/private** in `run/host-a/runtime-baseline.json`; never publish.

## SOURCE_IMPLEMENTED
- Prior HOST work reused: authenticated WSS, real 16 kHz/60 ms Opus upstream, RAM preroll 2 seconds, four-frame/250ms bounded queue, source sample sequence, transport epoch, touch/wake single activation, ack and STOP/output epoch.
- HOST-B boundary in `services/voice/host_wake_contract.py`: `AudioChunk(pcm_s16le,stream_epoch,sample_index,received_monotonic_ns)` -> `WakeEvent(stream_epoch,end_sample_index,phrase_id,detector_id,detected_monotonic_ns,confidence)`. HostCore is sole activation owner. New detector path verifies sample/epoch and prevents repeated/wrong-epoch/future wake. Legacy detector remains for old free tests.
- Optional **free downlink fixture**: `host_wake.free_downlink_fixture=true`, *default false*. Authenticated client requests `gobot_host_fixture` once per epoch; PLAN sends 24 kHz 60 ms Opus packets wrapped in separate position metadata; the send lock prevents binary/control interleaving. A concurrent sender permits continuous uplink while output plays. Scoped output epoch/playback_id and ordered start/drain ACKs reject stale control. This is not a Brain response or acoustic proof.
- Source-only latency tracker and firmware probing headers (copied from old HOST WIP): no transcripts, raw recordings or cross-device clock subtraction. Explicit device driver write-enter/return and task-drained stamps are **proxies**, not equivalent to audible first words. Source-only prepared B prototype has a mandatory finite admission claim before any provider operation; production remains disconnected.

## FREE_TESTED
- Local PLAN tests use real Opus encoder/decoder, authenticated 127.0.0.1 WebSocket gateway and fake device/detector, no outside service or paid calls. Includes simultaneous 16k input with 24k output fixture, queue bounds, receipt origins and replay/unauthorized fixture rejection.
- Original Issue #4 evidence reports 95 tests including an accelerated 1,800 audio-second replay. A real 30-minute Wi-Fi stream or physical device latency **has not been tested**.

## Delay after the question: source findings, NOT measured diagnosis
- `firmware/spotpear/gobot_turn_guard.h` transitions Capturing->Waiting after **800ms** from last detected speech (or 25-second safety cap). This is one configured device hangover, not the whole waiting time.
- Current B source `spotpear_realtime.py` traverses LiveKit/WebRTC, server VAD and audio commit, response creation and PCM, relay queues, Opus pacing and physical output buffer. Its thinking status starts on server_audio_committed; a device UI "sending" label cannot isolate the bottleneck.
- Historical gateway hello_ack=7.18ms was a **setup trace**, not measured speech-to-meaningful-voice latency. Required physical clocks: device last speech/VAD-end, device capture-end, gateway last frame, provider commit, first provider PCM, first Opus packet, device receive, first output-write, actual acoustic first meaningful word. Cross-clock subtraction is forbidden without alignment.
- Cold vs prepared B: a legitimate comparison requires parity of model, voice, instructions, context, endpointing, audio preset and max output tokens. Prepared B can incur charges before touch and requires separate Owner financial authorization. No paid ready session, prewarm or response was started.

## Status labels
- SOURCE_IMPLEMENTED: yes — software HOST foundation, PCM->WakeEvent boundary, free 24k downlink fixture, latency scaffolding.
- FREE_TESTED: yes — software loopback, fake client/detector, no network access to provider; see tests.
- BUILT: **NO** — no complete new ESP-IDF firmware image built in this task.
- INSTALLED: **NO** — live device and gateway remain untouched.
- HUMAN_ACCEPTED: **NO** — no physical microphone/display/touch/speaker feedback, real-time Wi-Fi soak or meaningful-reply p50/p95.
- Dependency: selected HOST-B detector integrates only through PCM->WakeEvent; physical port and installation require a new explicit Owner grant.
