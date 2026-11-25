# Sophia physical timer candidate v421

This is a source candidate based on the exact installed
`0.4.20-dev-sophia-duck-v4` application. The host code can play the free fixed
alarm through installed v420. A physical countdown requires the explicit
`hello.host_stream.timer_display = 1` capability added by this candidate.
Nothing in the preparation or native tests installs firmware or invokes a
model. A prepared source tree is not a built or installed application.

## Physical output contract

The authenticated current HOST v2 session accepts `gobot_host_timer` with
`session_id`, `epoch`, an increasing uint32 `revision`, canonical UUID
`timer_id`, `state` (`running`, `expired`, `clear`) and integer `remaining_ms`
in 0..86,400,000. A running timer requires a positive remaining duration;
clear uses an empty ID and zero. Older revisions and conflicting repeats are
ignored. An identical repeat does not restart the monotonic countdown.

The existing LCD timer runs on the local clock. Reconnection resets only the
wire revision fence; the deadline stays visible until a new authoritative
snapshot restores or clears it. A large countdown occupies the idle timer
view. The existing small badge remains visible with a primary conversation,
mute, weather or clock view. The renderer preserves each primary view.

`gobot_host_timer_ack` carries the same revision, ID and state, `rendered`, and
`evidence` equal to `native_framebuffer_invalidated` or
`native_framebuffer_unchanged`. It is produced after the real native renderer
callback. This does not prove LCD DMA, visible pixels or owner observation.
The Gateway validates the exact current transport and pending display update
before reporting a `timer_display_ack` to Brain.

The alarm uses the installed 24 kHz Opus cue path: a fixed 360 ms 660 Hz PCM
signal with fades, peak amplitude at most 2,200, and the current user volume.
The local output role is `timer_alarm`; the wire role is `cue` and
`whole_response=false`. Only its own claimed alarm receives started/finished
ACKs. It never produces an ordinary Brain playback completion, followup,
wake, transcription, speech generation or model request.

The signal waits for a fully idle physical pipe: no answer, thinking phase,
input/followup cursor, pending interrupt or mute. Pending output reports
`postponed` with a fixed reason in Gateway status. A new input or answer has
priority and waits for the real stopped/DMA receipt before taking the pipe.
Stop/Mute cancel or suppress the signal. A notice more than 120 seconds past
the timer deadline is suppressed. Durable claims prevent retry after an
unknown send or reconnection; a fresh snapshot still restores the display.

## Exact baseline and rollback

The parent manifest is `sophia_duck_v420_manifest.json`. The v421 manifest
pins its SHA, all 38 parent source hashes, 31 unchanged source paths, the SDK
configuration and all six protected binary assets. The patch changes eight
source files. Audio capture, WakeNet/AEC, Opus output, mute, interruption,
hardware volume, touch controls and receipt fences are unchanged.

The rollback app is the preserved v420 application:

- Version: `0.4.20-dev-sophia-duck-v4`.
- SHA256: `11956a9e4700c6c53f49ba03c3f3f12daae208d010c319305b2a9d704d52388e`.
- Size: 3,700,240 bytes; app offset `0x20000`, capacity 4,128,768 bytes.
- Prior PLAN path: `C:\Users\PLAN\gobot\HOST-INTEGRATOR-private\sophia-duck-v4-0.4.20.bin`.

Neither preparation nor rollback verification writes NVS, enrollment,
partition/OTA metadata, the inactive app slot or usage/accounting data.
The actual app-only installation remains a separate reviewed action.

## Private build contract

Local authoring has native `g++` but no ESP-IDF, Xtensa compiler or container
runtime. The complete project, existing SDK and private model assets must
stay on the previously authorized private builder. Historical records name
the builder `vmi3510488` and project roots under
`/opt/gobot-firmware/20261112-gobot-v1` and
`/root/gobot-sophia-private-20261117`. They do not establish the current v420
directory. Discover it read-only and select it only after the manifest's
complete baseline source/app checks pass.

Upload this new helper, manifest and patch plus the unchanged pinned parent
manifest to a new private directory. Do not alter the old v420 project.
Preparation accepts only an absent independent destination:

```sh
python prepare_sophia_timer_v421.py --source "$verified_v420_project" --destination "$new_v421_project"
```

Use the same cached container image and mount layout as the verified prior
build. The pinned image is
`espressif/idf@sha256:efc19fae2f52fc6873630c668da26aa834139a063b5fb73a46ebc0dbd217b587`.
The process must have networking disabled, at most two CPUs, 4 GiB memory,
two compiler jobs and a bounded wall time (30 minutes). The prior successful
incremental command was `idf.py reconfigure && ninja -C build -j2`. Check
the copied CMake cache's paths against that established mount before
reusing the incremental directory; do not modify SDK or fetch dependencies.
Save stdout/stderr to a new private build log.

After a successful build, run the installed ESP-IDF environment's
image inspection command on the new app, without any serial/port or flash
options. Choose the advertised `image-info` (v5) or `image_info` (v4) spelling
from the bounded `python -m esptool --help` output; do not repeat the build
because of a CLI alias. Confirm the ESP32-S3 target, v421 descriptor and full image
checksum. Then run this source-only verifier from the same uploaded bundle:

```sh
python verify_sophia_timer_v421_build.py --baseline "$verified_v420_project" --project "$new_v421_project" --image "$new_v421_project/build/xiaozhi.bin" --build-log "$new_build_log" --report "$new_build_report"
```

The verifier rechecks source, SDK and protected binary guards, exact original
app preservation, the candidate app descriptor and slot bounds, and one
exact embedded Sophia model. It emits SHA256/size and content-free evidence,
never private configuration or model bytes. It does not replace esptool's
image checksum check. Update the public manifest's build fields only from
that verified report; keep the binary and build log private.

## Verification and remaining physical acceptance

`tests/test_sophia_timer_output.py` exercises the real Gateway event handlers
with inert device/Brain transports and the actual local Opus encoder. It
covers bounded queues, idle postponement, stale expiry suppression, exact
cue ownership, Stop/Mute lock races, explicit-wake StopACK handoff, input
floor after DMA finish, cancel snapshots, and no replay of uncertain audio.

`tests/test_sophia_timer_firmware_native.py` reconstructs and hash-checks the
exact public source chain, applies the candidate patch, and compiles the
actual timer control/render receipt methods with ASan/UBSan. It also runs
the actual native screen renderer with synthetic glyphs to verify that a
timer badge does not replace a primary view. The private installed glyph
atlas, ESP toolchain and physical panel are outside these native checks.

After a concrete app is built and installation is authorized, physical
acceptance still needs: visible 10→0 countdown; timer cancellation and
reconnection restoration; a single audible cue at the user's volume in an
idle pause; no cue during Mute; Stop/manual wake while the cue plays; no
unexpected microphone opening; and no duplicated cue after a disconnect.
Native framebuffer and DMA receipts are supporting evidence, not a claim
that those owner observations have already passed.
