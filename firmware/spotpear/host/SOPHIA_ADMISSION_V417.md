# Sophia 0.4.17 admission display

This incremental source patch is based on the exact installed
`0.4.16-dev-sophia-unified-v4` app, SHA-256
`c6a50457a7aeec8ade964c4fb83781a6e7610ad9558343a7f72d595a40e41102`,
3,687,296 bytes. The candidate version is `0.4.17-dev-sophia-ui-v4`.
The parent V4 integration patch, manifest, private project and app remain intact.
The new manifest records build evidence; `docs/CURRENT_STATUS.md` owns deployment
and actual device acceptance. A source test or build is not a physical install.

## Changed behavior

An authenticated protocol-2 gateway can publish the selected mode's current
admission separately from the conversation phase:

```json
{
  "type": "gobot_host_admission",
  "session_id": "existing-authenticated-session",
  "epoch": "existing-transport-epoch",
  "input_allowed": false,
  "code": "scope_expired",
  "mode": "fast"
}
```

`input_allowed` must be a JSON boolean. The only mode values are `fast` and
`expert`. `available` requires true; every other accepted code requires false.
Stale scope and unnegotiated messages are ignored. Malformed data in the current
scope is rejected and produces an unavailable indication. It never changes
live capture, playback, the audio owner or the detector.

| Code | Persistent idle notice |
| --- | --- |
| `available` | None |
| `scope_expired` | Время теста истекло |
| `starts_exhausted` | Лимит исчерпан |
| `consent_required` | Нужно разрешение |
| `unavailable` | Разговор недоступен |

The detail line says «Быстрый разговор» or «Экспертный режим». It does not name a
provider that may differ from the current server configuration. Mute, active
conversation/playback, existing transient notices, timers and weather retain
their screen priority. The admission notice takes priority over the idle clock
and has no automatic expiry. An allowed update clears it. A new connection,
fault, mode shutdown or unmute reconnect resets admission to unknown.

With a known denial, a wake or touch is still forwarded to Brain with the same
authenticated scope. The device keeps the notice while Brain decides instead
of optimistically showing «Слушаю». A later authoritative `listening` state uses
the original rendering and input path. Continuous HostCapture, capture epochs,
detector sample positions and the server's pre-roll remain unchanged.

## Native evidence

The existing framebuffer renderer returns `Failed`, `Unchanged` or `Invalidated`.
Its drawing, geometry, atlas, allocation size and LVGL invalidation are unchanged.
A failure emits no successful admission render receipt. The device sends this
bounded receipt on an admission revision or native view/notice transition:

```json
{
  "type": "gobot_host_ack",
  "session_id": "existing-authenticated-session",
  "epoch": "existing-transport-epoch",
  "event": "admission_rendered",
  "admission_known": true,
  "input_allowed": false,
  "code": "scope_expired",
  "mode": "fast",
  "notice_rendered": true,
  "render_revision": 1,
  "render_evidence": "native_framebuffer_invalidated"
}
```

`native_framebuffer_unchanged` means the requested native page already matches
the renderer's last page. These receipts prove application/framebuffer state;
they do **not** prove a completed LVGL refresh, panel DMA or human-visible pixels.
The existing wake `ui_visible` wire event remains the legacy LVGL refresh proxy
on the permitted/unknown path; a blocked wake does not fabricate that event.

`GOBOT_STATUS` adds `GOBOT_HOST_ADMISSION_STATUS`: known, allowed, fixed code/mode,
revision, numeric native view, notice_rendered and numeric render result.
`GOBOT_HOST_ADMISSION_UPDATE` and `GOBOT_HOST_ADMISSION_RENDER` log fixed metadata
only. They do not log questions, PCM, credentials or provider error strings.
Render result numbers are 0 failed, 1 unchanged, 2 invalidated. Native view
numbers retain the existing enum: 0 ready, 1 connecting, 2 listening, 3 thinking,
4 speaking, 5 muted, 6 offline, 7 notice, 8 clock, 9 timer, 10 weather.

## Preservation and rebuilding

The patch changes only the two version declarations, application declarations
and UI/control glue, a small fixed admission helper, and the renderer's return
value. The existing Sophia `wn10_sophia` model, `DET_MODE_95`, microphone feed,
gain, sample rates, AFE, detector thresholds/cooldowns, continuous capture packer,
audio queues, playback fences and transport parser remain byte-identical.
NVS, enrollment, partitions, bootloader, assets and the inactive app are outside
the patch and outside any permitted installation of this candidate.

Run the public checks without a device or private model:

```sh
python -m pytest -q tests/test_sophia_admission_firmware_native.py tests/test_sophia_firmware_native.py
```

The C++ test compiles the helper extracted from the actual incremental patch.
It checks strict fields, stale scope, persistent notices, mute/output/timer
priority, reconnection reset and successful/failed/unchanged render receipts.
The previous capture clock and physical playback fence test also remains required.

On the existing private builder, run the preparer with an absent destination:

```sh
python prepare_sophia_admission_v417.py --source /private/preserved-0.4.16 --destination /private/new-0.4.17
```

The preparer requires the exact parent manifest, installed app, 33 source guards,
SDK configuration and protected binary assets before making a new isolated copy.
Build with the manifest's pinned ESP-IDF image, existing dependencies, networking
disabled and bounded parallelism. Verify the resulting app SHA/size/version and
all unchanged source/model/partition/asset guards before transfer.

Only root HOST-INTEGRATOR performs the separately guarded app-only installation
and rollback, using the strict 0.4.16↔0.4.17 installer. Never run generic `idf.py
flash`; it can write unrelated partitions. This firmware adds no expense grant
and does not authorize a paid provider call or a new recording.
