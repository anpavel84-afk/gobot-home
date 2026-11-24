# Natural timer duration — source-only candidate, 2026-11-24

## Owner incident and evidence boundary

Owner reports a question on Bulgaria's capital delegated to the expert, then
repeated timer requests. Sofia promised to try and subsequently reported an
invalid time format; owner reports no timer was created. No episode transcript,
tool arguments, error event, timer database, or current mode was inspected:
Desktop Commander explicitly reports the monthly quota exhausted and says not
to retry/reconnect. This is an owner-reported incident, not log-confirmed RCA.
Last verified deployment remains runtime 992039c88cb0453acceafd7156e54fbdbbee0d0f,
firmware 0.4.21. The candidate is based on documentation HEAD
c64dfbad95b2a604f9ccb424e4fccdef9eeb5cd4. No changes to PLAN, budgets, firmware,
or user data were made in this investigation.

## Defects in the installed source

- direct_timers instructs the voice model to copy duration verbatim. The
  source_timer_seconds gate requires an exact unique substring. Equivalent
  words, digits or unit conversions can be rejected.
- A missing optional duration_text requests clarification even if the actual
  accepted user transcript already supplies a complete duration.
- The older duration grammar misses several common Russian spoken forms.
- Generic gobot_tool uses a catalogue; its local timer route must share the
  complete-duration resolver, while preserving previous intent precedence.
- DirectTimers.current still requires selected_mode == fast. The reported
  transition from expert narration to the next timer request needs real-log
  inspection; this patch does not change expert dispatch.

## Candidate behavior

Parse the whole current, server-owned direct request (or authorized pending
duration reply). Accept a normalized model duration only when the independently
parsed seconds agree. If the optional argument is absent, use the unambiguous
original. Keep the prior exact-span validation for other utterances; do not
give the model authority to invent a value. Preserve capability/scope/current
turn and one-action receipt checks, no firmware, database or permission change.
Extend Russian words, hundreds, colloquial order, half units, composed hours /
minutes / seconds, decimal and compact notation. In a timer-duration context
two colon fields mean minutes:seconds, three hours:minutes:seconds; explicit
clock-time phrases are not durations. Missing units, alternatives, conflicts,
and out-of-range values must not create a guessed timer. The existing executor
range of 1..86400 seconds is unchanged. Generic catalogue priority remains
unchanged; only unmatched complete timer requests use the additional route.

Update tool instructions: call the local timer promptly, accept equivalent
duration representations, report the verified result rather than "I'll try",
ask one clarification when necessary. Existing physical display and expiry
pipeline remain unchanged.

## Verification and release gate

The parser file was copied byte-for-byte into an isolated local container and
its Git blob hash verified against the GitHub result
fb4d4c6bb53e0a0a913a04088d5d2002639782e4. 38 direct parser cases passed (17 legacy
and 21 additional) plus 24 equivalence/rejection/pending predicates. These are
62 focused Python assertions, not a server regression gate. A new pytest file
tests/test_sophia_natural_timer_duration.py records these cases and additional
mocked native-action and generic-route tests. Full project dependencies,
server regression tests, and live device validation were not run here.
No paid calls, no deployment, no flash. Need run the full established free
native/Windows gate, inspect the actual last expert-to-timer trace and compare
the new tests, then deploy during idle with existing safeguards. Confirm one
successful timer row, countdown ACK, signal receipt, and manual acceptance.
Do not claim the reported episode's cause or end-to-end repair before these
steps. Master and integration runtime must stay unchanged meanwhile.
