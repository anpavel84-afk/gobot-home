# HOST protocol v1 — required firmware port, NOT installed

This document describes the tested server contract in services/voice/host_stream.py.
Installed0.4.12 does NOT implement it. A mere config toggle is insufficient and
must not silently route normal touch through a fake HOST capability.

## Preserved hardware path

XiaoZhi/ESP-IDF, ES8311, I2S/AEC, Opus16k mono/60ms upstream, 24k mono/60ms
downstream, LCD/LVGL, existing gobot.ui scenes and physical touch. LOCAL/HOST is
wake placement, not A/B/C. Host switching is explicit and idle-only; no fallback.
One microphone reader and encoder; no second competing I2S input or raw recorder.

## Control framing

Same authenticated `/xiaozhi/v1/` endpoint and enrollment headers. Existing hello
has `host_stream` with exact typed fields:

```json
{"version":1,"capture":"continuous","frame_sequence":true,"local_wake_enabled":false,"local_feedback":true,"playback_epoch":true}
```

Server sends ordinary hello(session_id,24k output), then gobot_host_ready with a
fresh transport epoch and frame_samples960. Device returns gobot_host_ready_ack
with that session_id/epoch/frame_samples before starting upload.

Every raw Opus binary packet is preceded by a separate JSON gobot_host_frame:
session_id, epoch, seq(integer from0), sample_start=seq*960, sample_count=960.
Never prepend headers into Opus. **Generate these source counters in the capture/
encoder producer, not merely in the network sender**, so a dropped frame creates
an explicit discontinuity. Reset counters and decoder on reconnect. Do not replay
queued old audio. Source queue drops/age must fault and cancel an active utterance.
Server has four-frame bounded queue and250ms age guard; local source queue must
also be bounded. Two-second RAM pre-roll is history, not an added waiting period.

## Free local feedback

Server gobot_host_event(event=wake) identifies activation_id, feedback_id and
transport epoch; conversation_admitted=false. Device visibly acknowledges the
addressed call and plays its own local cue without opening a provider session.
Existing gobot.ui presentation.show payload is also sent.

Send gobot_host_ack(rendered) only from the actual render completion path, and
cue_started only from actual local output start. The reported send-to-ACK delay
is a control round trip, NOT acoustic keyword-end-to-screen latency.

Touch sends gobot_host_touch(gesture=activate/stop) through this same stream.
Single activation ownership deduplicates simultaneous touch and wake.
A wake event must never refill B or bypass C quarantine.

## Stop / media

Local detector consumes the ungated AEC output even while the conversation path
is masked. Ordinary room speech does not interrupt; a validated `Гоп` candidate
may request Stop. Server increments output_epoch and sends stop with command_id.
Device cancels output, flushes only that old audio epoch, invalidates late packets,
then reports stopped with feedback_id=command_id/output_epoch. Full provider
cancel/finalization remains separate and is NOT implemented by the free test path.
Playback reports use the same active epoch; listening rearm requires actual device
drain, not model response.done. Never forge a drained/stopped receipt.

Mute stops input and closes the HOST channel. Reconnect needs a new epoch and
fresh explicit readiness. Physical mute remains local even without PLAN.
The current server free-test `gobot_host_finish` clears bounded input and returns
idle; full Brain routing/handover is still a separate unfinished integration.

## Required candidate acceptance before installation

1. Implement the above in a COPY of preserved0.4.12, keep defaults LOCAL/FROZEN.
2. Preserve touch, display, audio ownership and enrolled settings; no model change.
3. Unit-test producer counters, drops, reconnect, cue/render receipt origin,
   duplicate wake/touch, Stop/late audio, mute and single-owner switching.
4. Build with the preserved pinned IDF image and correct build-status inputs;
   hash the app and check memory/partition budget. Do not label host G++ tests as
   a compiled ESP32 release.
5. Installation and active gateway switch require separate Owner approval.
6. Actual device wake/screen/speaker tests and30min real-time LAN soak remain
   NOT_RUN until those controlled steps. No paid budget is needed for local cue.


## HOST-A / HOST-B internal detector handoff (Issue #5/#6)

HOST-B should provide a factory returning a `HostWakeDetector` instance:
`feed_chunk(AudioChunk) -> WakeEvent | None`, `reset() -> None`.
The exact Python dataclasses live in
`services/voice/host_wake_contract.py`; contract_version=1.

- Input is unmodified decoded **PCM s16le mono 16kHz**, one 960-sample
  (60 ms) frame. No model-specific resampling is allowed in the transport;
  HOST-B owns any private detector resampling.
- `stream_epoch` identifies one authenticated WSS connection,
  `sample_index` is the beginning of the canonical frame in that epoch,
  `received_monotonic_ns` belongs **only to PLAN** and must not be compared
  directly with ESP32 time.
- WakeEvent carries one stable `phrase_id` and the exclusive
  `end_sample_index` of the detected phrase; stale/replayed/epoch-mismatched
  events are rejected. HOST-B must never call Brain or control the physical
  display/audio; `HostCore` owns activation and Stop. The old legacy detector
  remains in the software for compatibility during development.
- HOST-B may inspect receiver frame cadence but must not mutate
  `gobot_device_gateway.py`, `host_stream.py`, or firmware transport.

## Opt-in free output verification on PLAN

The new `host_wake.free_downlink_fixture` config flag is **false/absent**
by default, and does not change the installed gateway. On a separately
authorized HOST client, after ready/ready_ack, send
`{"type":"gobot_host_fixture", "session_id":"...", "epoch":"..."}`
exactly once per transport epoch. This is accepted **only** if the host_wake
policy explicitly enables that fixture and no utterance/feedback/Stop is in
flight.

The host replies with:
- `gobot_host_output_start`: playback_id, audio_kind=`fixture`,
  output_epoch, sample_rate=24000, frame_samples=1440, packet_count.
- For each output frame: JSON `gobot_host_output_frame` with playback_id,
  output_epoch, seq, sample_start=seq*1440, sample_count=1440; then a separate
  raw binary Opus packet. Do NOT prepend metadata to binary Opus.
- `gobot_host_output_end` with the playback_id/output_epoch/packet_count.
  Device `gobot_host_playback` ack must contain matching playback_id,
  the current output_epoch and `playing=true` at actual playback start.
  `playing=false` must not be acknowledged before physical drain and
  receipt of `gobot_host_output_end`. Stale ID or duplicate receipts fault.

The fixture is a short, low-amplitude local test tone. It is **not** a
Brain answer, wake recognition, acoustic verification, or approval to play it
on a household device. The current 0.4.12 firmware does NOT support this
protocol. Port, build, flash and gateway switching all require separate steps
and Owner permission. No paid session is opened by this fixture.
