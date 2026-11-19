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

`ExpertJobs` owns tasks independently of the transport subscriber. Signed bridge
deltas preserve item/phase/job metadata. Only verified partial/final assistant
answers are speakable; unclassified text waits for a completed assistant item.
The existing sentence buffer, formatter and Realtime-mini narrator produce early
ordered speech. Commentary, reasoning and arbitrary process stdout are excluded.
The full result, spoken version and physically acknowledged extent remain linked
in the Brain's conversation context. Completing an accepted tool job does not
create another `function_call_output` or a duplicate spoken Realtime response.

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
preserves that existing workflow and scope; it does not claim a shared authorized
B_WS browser-microphone conversation.

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
