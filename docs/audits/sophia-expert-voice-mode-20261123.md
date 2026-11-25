# Sophia expert voice mode: incident and correction, 23 November 2026

## Verified starting point

PLAN checkout was `da1e75c9ef6b0b14dd63e4444a7fcf7a1a9ecd9c`, with loaded runtime
`97514bedf9b9c4163cc4ab7844eda66a7ea5ff91`. The enrolled column was ready,
unmuted, capture connected, idle and in fast mode. The authenticated device
preview reported `expert_available=true`.

The effective permanent owner-terminal grant selected **ARGON_DEEP**, provider
**Antigravity**, model **gemini-4-argon-medium**, effort **medium**. Codex was
installed, its cached account and isolation evidence were present, and its
registered model/effort metadata was verified. None of the Codex profiles was
allowed by this current permanent grant. This distinction is essential:
installed CLI software, metadata readiness, device authorization, provider
quota and physical speech acceptance are separate facts.

`CURRENT_STATUS.md` records the owner's 19 November change to the Google CLI
after reporting an exhausted weekly Codex quota. The current check does not
establish whether that quota has since renewed. It neither changes that model
choice nor reuses an old finite Codex allowance. Historically accepted legacy A
speech used **SOL_HIGH / gpt-6.1-sol / high**. The registry also has SOL_XHIGH and
ASTRA_HIGH; registry entries alone do not establish a physical spoken run.

## Incident evidence

The existing owner-enabled, encrypted debug journal was examined on PLAN only.
The bounded 24-hour query read 462 non-text-delta rows and four transcript turns;
there were no decryption failures or limit truncation. Household text, audio and
the journal database were not exported or added to Git.

At **2026-11-23 19:45:55 UTC / 16:45:55 America/Sao_Paulo**, the final ASR text
mentioned expert mode. It was a polite ability/request form, not an exact byte
match for the owner's later reported imperative. On-device classification
confirmed an ability request and politeness, without a quoted/negative command,
a definition question or an attached second task. The native answer classified
as unable to switch while offering a more detailed answer. These are local
regex classifications, not a verbatim exported transcript. ASR remains an ASR
hypothesis; the answer's physical playback was interrupted/unconfirmed.

The final candidate parser was also evaluated against that exact encrypted
journal event on PLAN, in memory only: it returned `expert`. The tested parser
SHA-256 was `ffd88047f123b0e9c5b4a3d6ba6e0fae7472e84fe80762d049112b96d3f40519`.
Repository tests use synthetic variants, not a copied household utterance.

The turn generated native response/audio events, with no expert job/tool
submission. The subsequent mode event remained fast. The existing permanent
expert ledger independently contained **zero CLI attempts**, and the speech
ledger contained **zero expert STT/TTS operations** at the read-only readiness
check. The public cached handoff cue was present and checksum verified.

Private metadata report SHA-256:
`8b716fb66a4e617b1bc580a13d3f5c9285e76c4e05adfcc6a1ea80026f8a3073`.

## Root cause

`DirectSession.input_text()` handled local Stop but passed mode-selection text
to the native conversation. The Direct manager intentionally disables the old
`NativeHandoff`: it maintains one logical conversation instead of the legacy
transport handover. No replacement connected the final native transcript to
Direct's existing `select_mode()`.

The surviving `explicit_expert_request()` is a diagnostic signal for delegated
tasks, not a mode switch or expense authorization. Merely adding a word to that
detector would not repair mode selection. The old loose expert keyword helper
also accepts examples such as definition questions or negative instructions,
so it is unsuitable as a control parser.

A free reproduction using the real DirectSession and existing temporary-ledger
fixture sent the synthetic phrase “переведи меня в экспертный режим”. Before
the correction it left `selected_mode=fast`, `local_control=false`, emitted no
mode event, created one mocked native response and zero expert jobs.

The expanded integration gate uncovered two additional, previously unexercised
problems. First, the memory-era playback wrapper looked up only native response
turns; expert responses use a separate job mapping. A verified expert playback
receipt could therefore reach the follow-up guard with no turn and stop there.
The correction binds that continuation to the matching current expert job turn,
without allowing an old result to reopen capture after a newer question.

Second, `ExpertJobs.start()` passed the derived `session.owner_test_binding`
instead of the original offer binding into the expert budget. NativeSession's
fallback makes that derived value equal the client ID even on a legitimate
physical board. The permanent board budget correctly rejected it as a borrowed
phone binding, so metadata readiness did not prove executable admission.
The caller now passes `offer.owner_test_binding`, consistent with existing
native admission. The board's rejection of a real explicit phone binding,
its exact client check, policy validation and separate browser OwnerFullTest
accounting remain intact. No grant or budget validator is relaxed.

## Correction contract

The correction adds a bounded parser for complete, explicit mode requests and
connects it before native generation and ordinary question-memory retrieval.
It covers the reported imperative, short “включи эксперта”, natural switching
verbs, wake-name/politeness wrappers and complete polite ability requests.
Questions about a mode, negation, quotation and mixed command-plus-task text
must not become a mode switch by keyword matching.

The same local control covers stable expert transcription: `new_turn(query)`
calls `input_text()`, and the expert reader must stop after a local control
before starting a CLI job or enforcing its retired input epoch. Wake-fragment
resolution likewise must not turn deliberate control cancellation into an ASR
failure. The original STT usage is settled; the command creates no additional
native answer, CLI job, STT connection or generated confirmation speech.

The first accepted final transcript remains authoritative: a later conflicting
ASR event cannot replace a committed question with a control. A monotonically
increasing selection revision also makes a newer UI/API choice supersede an
older voice command still waiting for its read-only admission preview, even
when the UI reselects the current mode.

An explicit expert selection remains selected for subsequent manual wakes.
After an expert answer it returns to ready without automatically opening a new
STT/CLI operation. A separate one-task delegation from fast mode retains its
existing fast follow-up. Explicit Stop or a direct fast-mode request restores
fast selection. Current admission, selected profile, epoch, Stop/Mute and
stale-turn guards remain authoritative.

Commands select the **currently authorized expert**, not an invented Codex
fallback. This correction does not switch the permanent grant to another
provider. Web mode/admission events expose the selection; no new spoken mode
confirmation or physical LCD indicator is claimed.

## Existing expert speech path

The current Direct path is:

`verified CLI AnswerDelta → SpeechFormatter → SpeechTurn → marin`.

Only verified partial/final answer text enters speech; CLI commentary and
reasoning do not. The narrator is `gpt-realtime-2.1-mini`, voice `marin`, with
tools disabled and bounded text segments. Ordinary fast answers still use
native speech directly. The existing fixed handoff cue can play before an
actual expert task; it is not a confirmation of an empty mode switch.

## Validation and deployment record

See [the machine-readable evidence](../evidence/sophia-expert-voice-mode-20261123.json)
and the newest section of [CURRENT_STATUS](../CURRENT_STATUS.md) for the actual
gate and installation result. The initial audit is not installation evidence.
No automated paid CLI/model/STT/TTS trial is authorized or performed in this
correction. Model quality, provider quota availability and the complete live
physical expert speech cycle remain a manual acceptance item.
