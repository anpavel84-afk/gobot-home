# HOST-INTEGRATOR: implementation record

`docs/CURRENT_STATUS.md` is the sole current-state passport. This document records
the integration basis, contracts and reproducible checks, not a second live status.

## Basis and preservation

The source base is the backend actually running on PLAN:
`ec09960836a881e2312d1191a6607b486c997f58`. The documentation launcher commit is
included as a specification, not used as the implementation base. HOST-A public
transport source and all 64 privately preserved dirty/new source files were
integrated. The original HOST-A checkout is preserved. Its running Browser Lab
keeps its own root, budget, journals and HTTPS entry; only the panel entry and
navigation are added there during deployment. The two dirty primary-checkout
files (`AGENTS.md` and the earlier raw USB recorder) are not overwritten.

The owner explicitly selected the currently installed wake behavior. Fresh COM3
status and the matching private builder identify Sophia V4, not the handoff's V3:

| Property | Verified baseline |
| --- | --- |
| Version | `0.4.14-dev-host-b-sophia-mic-v4` |
| App bytes | 3,668,912 |
| App SHA256 | `254793df0426fecdfafbe5047674aef896568c236dd58330b6e4a47ff9c311a2` |
| Detector | `wn10_sophia`, `DET_MODE_95` |
| Detector input | Existing mono 16 kHz pre-AFE PCM |
| App slot | `ota_0`, `0x20000`, capacity 4,128,768 bytes |

Private backups remain on PLAN. Source exports contain no firmware binaries,
recordings, model weights, credentials, NVS or spending databases.

## Boundaries and flow

`realtime_ws.py` adapts the existing Brain and its original source-specific policy,
identity, tools and accounting. An authenticated empty socket waits for the actual
`session.updated` configuration confirmation; it does not reserve a paid start.
Input and Responses are admitted separately. Rotation preserves the logical
conversation and does not replay old tool IDs or create a second expert job.

Detached retention starts at the actual detach, independently of the last input
or the age of an otherwise healthy idle conversation. Cleanup rechecks that the
session is still detached and has no active expert before claiming closure. A
failed initial setup or an expired detached session can be replaced under the
same identity only when the session is provably empty. Admission-attempt markers
remain after an uncertain cancellation, so an unknown durable reserve cannot be
mistaken for an unused pipe. Used or explicitly closed conversations stay closed;
the existing scoped ledgers are never reset by reconnect. The existing limit of
three setup attempts per60seconds also bounds these empty replacements.

A prepared spare socket revalidates its owner/model/authorization scope and
receives current scoped context before adoption; an unusable spare is closed and
discarded. Socket identity prevents a retiring reader from marking its successor
disconnected. Authenticated status exposes bounded lifecycle metadata, including
detach duration, transport epoch, maintenance state and closed-session reason,
without provider text, audio or exception messages.

`sophia_audio.py` owns bounded RAM PCM history and one capture-clock cursor. The
v2 Gateway orders Opus before decoding, rejects gaps, drops duplicates, selects
pre-roll once, and sends burst followed by live audio through one stateful
resampler. `pre_roll_flushed` means local transmission, not a provider ACK.

`sophia_connection.py` negotiates the firmware capabilities before capture,
preserves the legacy handler for older firmware, and serializes the single
physical output. It keeps service cues, sentence receipts and whole-answer
receipts distinct. Only the whole-answer receipt plus the Brain guard opens the
continuation window. A cancel crossing the final DMA receipt retains ownership
until the next output-generation `stopped` ACK, preventing an unintended follow-up.

The firmware uses the same V4 detector and microphone feed. Its independent
capture sample clock, stream epochs and real I2S DMA fences bind input and output
receipts. Capture is muted during Mute; the control heartbeat remains available.
The final firmware manifest is the source of build hashes and size evidence.

Display timing has a different evidence boundary from audio completion. The
existing `host_rc1_render_ack.h::OnNextNativeRefresh` uses `LV_EVENT_REFR_READY`.
Pinned LVGL can emit that event after submitting the final single-buffer strip
but before its SPI DMA completes. The installed protocol's legacy `ui_visible`
name therefore does not establish first visible pixels or final panel transfer.
The Gateway reports `last_wake_lvgl_refresh_ready_ms` with the explicit basis
`lvgl_refr_ready_not_panel_dma`; both timestamps are on the ESP clock, so network
delivery is excluded. No first-pixel target is claimed from this measurement.

`ExpertJobs` owns tasks independently of the transport subscriber. Signed bridge
deltas preserve item/phase/job metadata. Only verified partial/final assistant
answers are speakable; unclassified text waits for a completed assistant item.
The existing sentence buffer, formatter and Realtime-mini narrator produce early
ordered speech. Commentary, reasoning and arbitrary process stdout are excluded.
The full result, spoken version and physically acknowledged extent remain linked
in the Brain's conversation context. Completing an accepted tool job does not
create another `function_call_output` or a duplicate spoken Realtime response.

CLI execution and audio delivery have independent deadlines. A bounded producer
reads verified answer deltas under the original job timeout and retains at most
the admitted result-character limit in RAM. Playback backpressure cannot spend
the deadline of an already completed CLI request. The narrator retains its
cumulative 45-second provider-I/O budget; only time suspended while the consumer
plays a yielded PCM chunk is excluded. A delivery stall is bounded to five
seconds, suppresses narration and retains the CLI text without retrying the job.
Explicit cancellation closes both producer and renderer. These changes do not
extend grant validity, model limits, reservations or allowed operation counts.

## Expense and privacy behavior

`unified_voice_budget.py` uses existing scoped authorization and ledgers. It does
not renew or create grants. Owner STT/TTS retain their established origins.
Developer STT consumes the separate transcription allowance, rather than borrowing
developer Realtime credits. Each narrator Response has its own atomic reservation
and measured settlement. Missing or malformed final usage retains the estimate;
neither a reconnect nor a failed response silently resets the allowance.

`remember=false` retains temporary conversational context in RAM. New direct-voice
diagnostics use `ContentFreeJournal`: text, tool arguments/results, prompts and
provider payloads cannot reach the durable journal, including when the original
opt-in journal is enabled. Existing HOST-A/legacy journals are not reconfigured.
This is an application retention behavior, not a claim about provider retention.

The exact public cue “Передаю задачу эксперту” requires validated text, model,
marin voice and WAV SHA. Inspection found no matching entry in PLAN's existing
100-clip cache. A missing cue is explicit and never triggers automatic synthesis.

The freshly inspected B grant is expired with two nominal starts unused; C has
unconfirmed prior finalization. Existing expert/STT/narrator authority does not
authorize this physical column's required live acceptance. Browser Lab's separate
metered allowance is not transferred. These are live-test blockers, not reasons to
skip source, build, recovery or free physical verification.

## Interface

The existing private HTTPS application gains `/sophia`, serving the actual Brain
and Gateway state. Fast/expert mode, Stop and Mute operate on the server-bound
enrolled column. The page cannot write identity, policy, credentials or grants.
Loopback/origin checks prevent cross-site control. Its Browser Lab comparison link
preserves that existing workflow and its separate metered allowance.

The browser source uses the same Brain direct-voice contract through a bounded
server proxy. The private Serve proxy presents a loopback peer for every browser;
that peer cannot distinguish individual browser identities. The explicit Connect
action therefore creates a separate guest row through the existing DeviceStore
and returns a server-signed host-only cookie. Status/control/WS read only that
exact binding, with no shared-loopback fallback. Binding creates no spending
grant, owner/adult profile, personal-memory access or microphone permission.
An absent binding or grant blocks a new operation before provider access; no
column, PHONE or Browser Lab identity is substituted. Opening the page or
selecting the browser source never creates a profile or requests a microphone.
Explicit Start is required, and PCM waits for the server's listening acknowledgement.
An existing expert can be reattached as an output-only subscriber without a new
wake or microphone. Source changes occur only at an idle boundary.

Browser output credit allows four 100-ms PCM frames in flight. Large upstream
chunks are split before the credit check. Sample fences, response ownership,
monotonic progress and elapsed playback time reject early or unrelated receipts.
Control processing is independent of the media writer, so Stop/Mute clear the
queue even while output waits. WebAudio completion is explicitly proxy evidence,
not an acoustic measurement. The input worklet permits at most eight unconsumed
40-ms frames, rejects stale/duplicate acknowledgements and fails closed if the
main thread stops consuming. Temporary transcripts remain in browser RAM.

## Checks and recovery

The synthetic combined fixture runs real DirectSession, ExpertJobs and the speech
pipeline with fake providers. It verifies early answer audio, cue and answer DMA
receipts, rotation without another CLI job, RAM context and guarded continuation.
Separate cases cover cancellation races, bounded audio, source exclusivity,
authorization expiry/revocation, measured accounting and a real enabled journal
that must not persist a private test phrase. Test sets overlap; their counts must
not be summed into a fictitious total.

On PLAN, `scripts/audit_agents.py` refreshes the installed CLI isolation evidence
against a local mock provider with zero real model requests. The current source
digest must match; an old evidence hash cannot be copied or fabricated.

`tools/sophia_v4_app_install.py` accepts only the exact V4 and final manifest
candidate. It defaults to read-only preflight, requires a current-image ROM match,
reads only partition and OTA metadata, and permits one address-restricted app
write with verification. Reversing those two known images performs an ordinary
restore. A partial/unknown write stops rather than being blindly retried.
No partition, OTA selection, NVS or factory-reset write is offered.

`tools/sophia_hardware_fixture.py` is a finite diagnostic replacing the stopped
production Gateway on its existing enrolled TLS port. Its in-memory Brain peer
has no provider or key access. A quiet synthetic tone checks the production Opus
path, physical DMA receipts, capture after the guard, Stop, Mute and a new stream
epoch. It saves numerical evidence only. It does not prove real provider latency,
the marin transition, wake quality in a household or human acceptance.

Actual install, physical results, remaining live-test blockers and the exact
continuation/rollback checkpoint belong in `docs/CURRENT_STATUS.md`.

## Resuming finite provider acceptance

`scripts/sophia_voice_grant.py status --epoch <prepared-epoch>` is read-only.
The exact prepared proposal and its SHA are recorded only in the current-state
passport. A disabled proposal is not an authorization. After the owner approves
that specific scope, `authorize --epoch <prepared-epoch>
--owner-approved-proposal-sha256 <approved-sha>` starts its one-time validity.
The operator then uses the explicit `cue --execute` action once and checks the
resulting fixed cue's text/model/voice/SHA. A missing or failed cue never causes
an automatic second provider request.

Before mounting the new profile, retain the current mount/config hashes and
verify idle native/direct sessions and owned process identities. The profile
mount and the hardware expert-consent flag must change together during this
controlled update; old B/C/PHONE/Lab ledgers remain unchanged. Fresh status must
show the actual newly authorized scope and its untouched counters before input.

The finite physical acceptance covers a short fast answer, an accepted expert
handoff, an explicit expert dictation, streamed marin output, interruption,
whole-answer DMA receipt and a follow-up using the same temporary context.
Compare the configured server450 and semantic-high endpointing only within the
admitted finite response count. Use public test prompts and retain numerical
timings/usage, without turning private answers or raw microphone audio into
durable fixtures. Report sample counts and warm/cold cases; proxy DMA or LVGL
events do not establish acoustic or first-visible-pixel latency. Unknown usage
retains its reservation and stops retries. Human voice-quality acceptance stays
separate from these measurements.
