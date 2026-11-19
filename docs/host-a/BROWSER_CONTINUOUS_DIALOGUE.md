# HOST-A Browser Voice Lab: continuous two-way conversation (A-only)

**Date:** 2026-11-17; **scope:** isolated Browser Voice Lab on Windows PLAN.
The physical Spotpear, RC1-r3 firmware, COM3, and HOST-B are NOT modified.

## UX and state transitions

1. Keep browser microphone open (iPhone or PLAN PC) as a local-only wake
   sensor. Initial `Моника` may follow a short salutation like `Окей`,
   `Слушай`, or `Привет`. Real Vosk handles PCM16 frames; no cloned ASR.
   Weak name aliases such as `модников`, `модика` and `маньяка` are
   limited to three probes per browser session. Random interior mentions
   like `фильм про Монику` are not accepted as an address candidate.
2. The existing verified Monika WakeEvent starts bounded, owner-budgeted
   real-audio `gpt-live-transcribe`; cloud must independently hear the exact
   canonical name, not a Vosk alternative. Failure -> no Brain/action.
3. Accepted question -> **existing** GoBot Brain `Service` (same instance,
   conversation_id and user/device id across turns) and existing
   `voiced_events`+OpenAI `marin` voice. Original Brain local tools handle
   time and timers; ordinary questions use existing OpenAI fast path. Native
   heavy specialist agents / home control are NOT automatically enabled
   without their own permission/infrastructure.
4. When the actual browser sends `playback_drained`, open a **16 second**
   local microphone-only window (`followup` state). No OpenAI socket is open
   in that idle state. A 400ms echo guard avoids triggering on speaker tail.
5. Local PCM amplitude >= an adaptive floor on three consecutive 60ms frames
   begins a **new turn** without repeating the name. A one-use
   `FollowupPermit`, bound to the same original verified wake, browser
   transport epoch, conversation id and wall deadline, is consumed. It
   cannot be replayed or used after idle expiry.
6. Stream the canonical PCM16 utterance into the **same**
   `CloudTranscriber._run` engine and budget as the original turn;
   `input_audio_buffer.commit` happens after 14 silent frames (~0.84s)
   or 9.6s maximum speech. Here cloud returns `FOLLOWUP` rather than
   asserting a second new-name verification; the existing Brain handles
   the follow-up text in the same conversation. When response is heard,
   re-open the same short 16-second window.
7. If the window expires without speech, return to `ready` (wake-only).
   The browser mic stays open but **no paid cloud standby**. The entire
   REAL Browser Lab is still bounded to 300 seconds per WebSocket session.

## Budget / safety

REAL still needs the browser's explicit paid-session confirmation, a
validated first local Monika wake and exact first cloud name confirmation,
and uses the **shared HOST-A owner ledger** (3000 reserved seconds/$3 local
estimate, 8 maximum Brain+TTS real turns). These are local conservative
limits, not provider-enforced caps; claims are never refunded after errors.
STOP/disconnect invalidates the permit, flushes owner-approved text logs,
and cancels any active cloud task. Only the browser source/sink is active,
not physical Spotpear.

Private full transcript and numeric latency files stay in
`run/host-a/browser-lab/` under PLAN Windows ACL. Nothing there is
published to GitHub.

## Acceptance

- Address matcher unit tests include `Окей, Моника`, `О кей, Моника`,
  weak alternative word limits, and false-positive avoidance.
- Finite local VAD, no-name cloud follow-up using fake OpenAI WS,
  one-time permit replay and expiry tests: PASS.
- Existing original Brain (clock -> timer) and same-conversation context:
  PASS with mocked speech PCM, no external API.
- Actual loopback browser WSS + existing Vosk + MockCloud protocol,
  **two turns with one initial wake and two browser playback ACKs**:
  PASS, 0 errors. Neither hardware nor paid OpenAI invoked.
- German Tailscale peer HTTPS `https://plan.tailffc57c.ts.net/`
  returns HTTP 200 with verified TLS and serves new UI and WSS scheme.
- First REAL human iPhone multi-turn acceptance and latency remains
  **UNVERIFIED**. Review full PLAN journals after owner testing.

## Owner test

Refresh Safari with Tailscale enabled. Choose REAL and approve the
existing owner grant. Ask `Окей, Моника, сколько времени?`. Wait for
natural audio to finish; the UI must show `Слушаю продолжение` and the
16s countdown. Ask `А что ты умеешь?` without the name. Then try a
different scenario `Поставь таймер на две минуты`. Remain silent until
the UI returns to `Ожидаю «Моника»`. Report any missing audio or
spurious wake; collect `followup_wait`, `followup_speech_start`,
`followup_audio_commit`, STT/Brain/TTS times and exact texts from the
local JSONL file. No unattended paid tests.

## 2026-11-17 weak-name detection v2, full FINAL acoustic context

The Owner's exact failure was recorded near the 297th second of the former
300-second browser session: a Vosk partial and final BOTH said a variant
of `привет моник ...`, but the local detector did not activate because
it expected two *different* stable partial updates. As of this update,
a matching Vosk endpoint-final is sufficient to emit a **candidate**
even when identical to the previous partial or the sole recognizer
hypothesis. It does NOT independently authorize Brain execution.

Owner-requested weak candidates include `моник`, `монки`,
`модников`, `модеников`, `модика`, `маньяка` and `мой`,
`мой ник`, `мойка`, `мойник`, plus bounded short `мой*`
spelling variants (single whole Cyrillic token, 3–8 chars).
Candidates are checked only in an address slot, for example after
`привет` or `окей`. Ordinary sentence mentions are excluded.
The existing max-3 weak probes per Browser Lab session and global
$3 owner estimate cap remain enforced. Other words such as `монитор`
are not silently added.

A new browser-only 5-second PCM pre-roll retains actual name audio
when Vosk emits a long complete utterance only at its final endpoint;
the shared physical/Spotpear WakeGate still defaults to 2 seconds.
The unchanged CloudTranscriber protocol is allowed up to 5-second
replay only when explicitly configured by Browser Lab. No transcript
is substituted for independent real-audio verification. REAL is now
limited to a 10-minute local browser connection (was 5 minutes);
paid per-turn reservations and total owner limits are unchanged.

The browser shows locally detected `weak_candidate_seen`, the
`candidate_notice` sent to the real cloud, and a clear warning if
the **eight** previously authorized Brain+marin paid turns are used.
After the eight Brain turns, REAL may still provide STT-only testing
within the remaining shared 3 USD estimated limit, but cannot deliver
a new paid Brain/TTS reply without explicit new Owner authorization.

Regression: 165 selected tests pass, Node JS syntax PASS, actual local
browser WSS MOCK speech -> Vosk -> cloud-fake -> followup PASS; REAL
silent WSS handshake with `budget_warning` PASS. The independent
German Tailnet client confirms HTTPS 200, TLS verification 0 and
new UI is served. No paid calls, Spotpear or firmware work during
the implementation and validation.
