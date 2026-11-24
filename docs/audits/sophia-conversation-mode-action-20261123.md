# Sophia: conversational mode action, 23 November 2026

## Request and starting point

The owner requested that the conversational model recognize an ordinary request
to involve the expert at any point in a conversation and perform the actual
mode change. Requiring a fixed phrase is not an adequate product contract.

The starting checkout is `0ff1ebfa6793687c3e9d4a00069f18851c5d8931`; the loaded
PLAN runtime is `9d8b2a73bf9446644923d68cd0b3d88593224625`. That version already
has a deterministic handler for complete direct mode commands, persistent
expert selection, a current-turn playback guard, and the corrected original
board offer binding for the expert budget. Those changes remain in place.

The missing layer is a native action available to the conversational model.
Direct's configuration has `expert_propose`, `expert_start`, and `expert_cancel`,
but no mode-selection tool. Legacy mode instructions are only configured when
the old transport handoff exists; Direct deliberately does not use it.

## Implemented behavior

The Direct conversation receives a `conversation_mode` function and explicit
instructions for interpreting the current user's request. The native model
interprets intent; the server executes and returns the actual result. A second
complete-command regular expression is not used to reject natural paraphrases
after the model has chosen this action.

The implementation distinguishes a persistent mode choice, a mode choice with
the question in the same utterance, and one-question expert delegation. A
reference to the previous question must resolve to a real eligible user turn
in the same conversation. Tool arguments cannot provide a replacement task,
credentials, arbitrary executor, or permission flag.

The tool accepts `mode=fast|expert`, `task_source=none|current|previous`, and
optional `scope=conversation|one_question`. The default scope is conversation;
one-question scope requires an actual expert task and preserves the current
selected mode. Fast selection accepts only an empty task and conversation scope.
An optional `requested_provider=configured|codex|antigravity` is a semantic
constraint, not a grant or a model selector. A mismatched provider is rejected.
The model distinguishes a requested executor from provider names that merely
appear in the subject of a question.

Only a real current-user request may invoke the action. Instructions tell the
model not to treat mode descriptions, negations, quoted examples, stored
context, tool results, or its own suggestion as an instruction to switch.
The existing proposal-and-user-confirmation flow remains appropriate for an
expert suggested by the model. An explicit user request does not need another
ritual confirmation of the same action.

## Server responsibilities

The source of authority is an actual correlated function call from the current
response and its current final user transcript. The coordinator records the
turn, transcript revision, input epoch, transport epoch, mode-selection revision,
and conversation binding at event reception. It checks them again across
asynchronous boundaries. A newer Stop, mute, detach, question, transport, or
mode selection must invalidate the pending action; a replay must not create a
second job.

Selecting a mode alone must not start CLI or open a second transcription.
For a task handoff, the server transfers the existing question and permitted
context to the existing expert pipeline. It does not manufacture an STT
reservation. The playback/execution turn belongs to the current action, while
the source question has separate provenance.

The old native response can be retired without cancelling the authorized
user task. Late cancellation acknowledgements or audio from that old response
must not cancel or replace the expert answer. Existing expert budget, isolation,
ACL, task bounds, narrator, and physical playback receipts remain authoritative.

A model-driven pure selection receives one budgeted native acknowledgement of
the actual tool result, with tools disabled and a 384-token output limit. This
uses the existing conversational voice and its current operation. The original
deterministic transcript shortcut retains its previous behavior. A task handoff
uses the existing cue/expert narrator instead of adding a second native answer.
If selection succeeds but task admission fails, the result reports those two
outcomes separately. A denial or exhausted acknowledgement allowance must not
be presented as an accepted expert task.

Previous-question handoff keeps the exact source question and the exact current
instruction as separate bounded packet data. The expert is explicitly told
that the server has already accepted the routing action and should answer the
substantive question. An unconfirmed fragment of the previous answer is not
labelled as already heard. A previous current-question handoff remains eligible
through its stored source reference; pure selection and ambiguous standalone
acknowledgements are not guessed into new questions.

## Actual executor and scope limits

The current owner-terminal grant selects **ARGON_DEEP / Antigravity /
gemini-4-argon-medium / medium**. This change does not switch it to Codex.
The tool must report the actual selected executor. An explicit request for an
unavailable different executor must not silently run the current one instead.

The current fast conversational model can interpret natural mode requests.
Idle persistent expert input still follows the separate STT-to-CLI path, whose
CLI tools are disabled. Existing direct voice commands and Stop provide exit
from that path. This work does not claim an additional semantic classifier on
every expert utterance. The established wake interruption barrier remains in
control of physical capture and playback; firmware is unchanged.

## Validation boundaries

Automated checks use synthetic user text, provider events, isolated temporary
ledgers, and mocked external model/CLI/speech implementations. They can establish
correct orchestration, correlation, source selection, cancellation, and spending
guards. They cannot establish natural-language model selection accuracy for
every paraphrase, current provider quota, acoustic wake acceptance, or a real
spoken expert response.

No household transcript or audio is exported. No developer model trial,
additional grant, policy reset, firmware installation, or change of executor
is implied. The exact tested source, Windows gate, deployment outcome, and
remaining manual acceptance are recorded in
[the evidence record](../evidence/sophia-conversation-mode-action-20261123.json)
and [CURRENT_STATUS](../CURRENT_STATUS.md).

## Installed result

Source `150ec61a3b098dd669a47db83acae2fbc747cec9` was installed on PLAN and
published to the feature and integration branches. The final read-only
postcheck at **2026-11-24 02:47:46 UTC / 23 November 23:47:46 BRT** confirmed
that exact loaded runtime, a ready attached physical transport, unmuted
capture, no active turns/inputs/experts, and no Gateway error. Counters advanced
by 249 packets, three application keepalives and three device controls across
the 14.125-second postcheck. The existing admin was verified locally and over
its owner-only private HTTPS address.

The same 58-file gate passed locally (**999 passed, one Windows-only skip**)
and on native Windows (**1000 passed**, including actual DPAPI). The source
includes 72 new regression cases. The final independent review found no
remaining blocker; accepted-job Stop/Mute/detach/reattach were also checked
with mocked providers. An older child-profile test outside this declared gate
has a fixture without an allowed expert grant; its earlier rejection was
reproduced with the base ExpertJobs module and was not weakened.

Before deployment, the previous transport had recovered but its old state
still said disconnected. Two short observation probes stopped before any
control action. A six-second interval spanning the Gateway's five-second status
publication confirmed the same idle session, same transport and advancing
packets. One supported Stop reconciled the state before the unchanged strict
deployment checks. No readiness guard was relaxed. This is an operational
recovery record, not a claim that the old reconnect-state defect was separately
redesigned by this change.

The deployment preserved 72 policies, 23 usage databases, one profile database,
two configuration files, both worktrees' existing work, and the original
working-memory policy and checkpoint bindings. Two temporary exchanges were
restored without error. Existing production usage was unchanged; expert
attempts and expert speech operations were still zero. No rollback, master
merge, firmware change, grant change, automatic paid trial or household-text
export occurred. Actual natural-language tool selection and physical expert
speech remain untested by this installation procedure.
