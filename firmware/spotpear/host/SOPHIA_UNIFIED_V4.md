# Sophia V4 unified firmware integration

This is a **source-only extension of the firmware actually installed on Spotpear**, version
0.4.14-dev-host-b-sophia-mic-v4. The earlier V3 audit is not the build base. The public repository
does not contain the private application, model weights, enrolled configuration or transfer pack.

## Preserved baseline

The installed V4 app is 3,668,912 bytes, SHA-256
254793df0426fecdfafbe5047674aef896568c236dd58330b6e4a47ff9c311a2.
The successful candidate is recorded in sophia_unified_v4_manifest.json; that file binds the
source patch, exact source inputs, pinned ESP-IDF image and the particular built app.

The model implementation and PCM tap are byte-identical to V4. The detector remains
wn10_sophia with DET_MODE_95, mono signed PCM16 at 16 kHz. The one existing microphone reader
still reads 160-sample blocks and selects the same microphone channel before the AFE. Neither
microphone gain, thresholds, native model frame size, AFE configuration nor sample rate changes.

Private builder verification compared all 29 baseline source guards and 16 patched source
guards. It also compared sdkconfig, dependencies.lock, the model, the older local model,
partition table, OTA initialization, bootloader and generated assets. The exact 383,508-byte
Sophia model occurs once in the candidate app. The preserved V4 source tree and original app
were not overwritten.

## Runtime behavior

A single bounded packer copies the same pre-AFE samples into 960-sample Opus input frames.
It does not add an I2S reader or feed samples back through the detector. Encoding remains on
the existing Opus worker. A gap or stale frame closes the transport and requires a fresh
stream epoch instead of concealing missing samples.

The device starts with the V4 local detector. It probes the existing authenticated enrollment
endpoint for protocol 2; no endpoint or mode is written to NVS. Continuous LAN capture starts
only after a valid protocol-2 ready exchange. An unavailable, incompatible or broken peer
returns to LOCAL and permits a later probe.

DNS/TLS/hello run on one temporary sophia_connect worker, with an 8 KiB stack and priority 1.
The application task, microphone task and display remain runnable. The application-level v2
server-hello timeout is 2.5 seconds; the existing transport's own TCP/TLS/WebSocket timeouts
remain in use. No second socket or second Brain owner is created.

If Sophia wakes while that idle probe is running, the application immediately renders the
Listening view and preserves V4's existing question buffer. If connection succeeds, that first
question uses the existing LOCAL handoff and unified negotiation is retried after the turn.
If connection fails, the device reports the connection failure and restores local wake.
A real LVGL refresh receipt is logged as SOPHIA_COLD_UI_VISIBLE; this is not an inferred display
timestamp. Installed-device measurement is still required to establish an actual latency.

GOBOT_BWS_ON selects negotiated protocol 2 through the enrolled endpoint.
GOBOT_BWS_OFF or GOBOT_HOST_OFF restores LOCAL without a persistent setting change.
The old GOBOT_HOST_ON test-URL selection remains a separate diagnostic path.
GOBOT_STATUS additionally prints GOBOT_HOST_V2_STATUS with actual capture and queue counters.

Mute stops capture, clears queued audio and decoder work, and leaves a control-only socket
with periodic aggregate telemetry. Unmute closes that transport and negotiates a new stream
epoch; pre-mute PCM cannot enter the next input cursor.

## Protocol 2 boundaries

All controls carry the authenticated transport session_id and epoch.

| Message | Relevant fields and boundary |
| --- | --- |
| gobot_host_ready | protocol=2, frame_samples=960, pcm_stage=pre_afe, wake_location=ESP |
| gobot_host_ready_ack | protocol=2, stream_epoch, sample_start=0, frame_samples=960, pcm_stage=pre_afe |
| gobot_host_frame + binary Opus | stream_epoch, frame_id, sample_start, sample_count=960; strict monotonic source clock |
| gobot_host_wake | wake_id, stream_epoch, detector_sample, detector_monotonic_us, callback_monotonic_us |
| gobot_host_ack | event=ui_visible, wake_id, device_monotonic_us, callback_monotonic_us after actual LVGL refresh |
| gobot_host_output_start | response_id, playback_id, output_epoch, kind=answer or cue, streaming=true, packet_count=0, Opus 24 kHz, frame_samples=1440 |
| gobot_host_output_frame + binary Opus | seq, sample_start=seq×1440, sample_count=1440 with the same output owner |
| gobot_host_output_segment_end | segment_id and cumulative pcm_sample_end at 24 kHz |
| gobot_host_output_end | actual packet_count and whole_response; a cue cannot end an answer |
| gobot_host_output_cancel | current output owner and current output_epoch |
| gobot_host_playback | state, response_id, playback_id, output_epoch, whole_response and the evidence appropriate to that state |

Output epoch starts at zero per transport and increments only for an accepted cancellation.
A physical stop sends action=stop; it does not independently increment the epoch. Exact
cancellation retries are idempotent. A cancel crossing the final drain of the same output
owner is accepted, while an old owner cannot cancel a new output.

The progress receipt reports packets_consumed as driver submission credit. It does not claim
that those packets were already audible. playback_started likewise identifies driver
submission, not measured acoustic onset.

A sentence receipt uses a fixed fence from the first written Opus packet covering its final
PCM sample. The fence is satisfied only after actual I2S on_sent interrupts pass a complete
DMA ring plus one descriptor after that write. This is conservative digital output evidence.
The bounded ledger holds up to 16 pending sentence fences. Later metadata may produce a
later receipt, never an earlier one.

segment_finished with segment_id confirms that sentence only. A drained cue reports
segment_finished without segment_id and whole_response=false. Only a whole answer reports
playback_finished with whole_response=true. Whole completion also includes stream_epoch and
sample_floor in the microphone capture clock, so the gateway can exclude output echo.

Cancellation flushes decoder queues and waits for software and I2S DMA drain before sending
state=stopped with the cancelled response/playback IDs and the next output epoch. The gateway
must retain that owner until this receipt. It must not open a follow-up from a cue, sentence,
late cancelled completion, or provider-generation-done event.

gobot_host_stats contains aggregate queue sizes, encoding drops, input/encoded frame counters
and free internal/PSRAM memory. underrun_measurement=not_instrumented is intentional: queue
statistics are not presented as a measured hardware underrun count.

## Rebuilding and verification

Run the public source/native test without private firmware:

    python tests/test_sophia_firmware_native.py

On the existing authorized private builder, prepare a new isolated directory:

    python prepare_sophia_unified_v4.py --source /private/preserved-v4 --destination /private/new-candidate

The utility refuses an existing destination, validates exact baseline checksums and applies
only the public patch. Build with the pinned ESP-IDF image from the manifest, the existing
private dependency cache, and networking disabled. Keep the original project unchanged.

The candidate passed the native capture-clock, cancellation, stale-owner, final-drain race
and segment-fence tests and the ESP-IDF 6.0.1 app build. The build fits the existing 0x3f0000
application slot at 0x20000. The binary hash in the manifest identifies this specific build;
future rebuilds must be hashed and validated independently.

This document does not authorize a flash command. Root HOST-INTEGRATOR owns the guarded
app-only installation, rollback and physical acceptance. Do not use the generic idf.py flash
command printed by ESP-IDF: that generated command also writes unrelated partitions.

Required device evidence includes actual wake-to-visible timing, microphone continuity,
cue/answer/segment ownership, cancellation, mute/unmute fresh epochs, DMA completion and
resource stability. The source/build results alone do not prove acoustic quality, human
wake accuracy, measured acoustic onset or end-to-end conversation success.
