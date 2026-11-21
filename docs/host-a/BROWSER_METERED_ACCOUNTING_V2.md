# HOST-A Browser Voice Lab — metered budget v2

Date: 2026-11-17. Scope: **only** the experimental Browser Voice Lab
on Windows PLAN, tailnet HTTPS 443 -> loopback 18811, not Spotpear or
the production GoBot Brain. Implemented because virtual $0.35 fixed
holds falsely exhausted the 8-turn trial and the $3 local estimate
while only 136 seconds of actual wall time had elapsed across 28 calls.

## Immutable legacy / separate browser overlay

- Original trial ledger remains unchanged:
  `run/host-a/paid-trial-20261116/ledger.json`
- New **local-only**, Git-ignored browser overlay:
  `run/host-a/paid-trial-20261116/browser-metered-ledger-v2.json`
- New module:
  `services/voice/host_a_browser_metered_budget.py`
- Transparent TTS provider response.done usage reader:
  `services/voice/host_a_browser_usage_probe.py`

The original v1 ledger is deliberately kept byte-for-byte immutable
and remains authoritative for *physical* A test tools. The v2 overlay
imports historical rows under a snapshot SHA-256. When an older v1 row
is added later, the overlay imports it on next status check; an active
unfinished legacy row fails closed.

## What is / is not the OpenAI bill

The OpenAI dashboard screenshot from the owner showed a project total
of $2.96 spent in November as of the screenshot, within the $60
monthly project limit. It includes all model usage in that project,
not necessarily just Browser Lab; it cannot be directly equated with
the local trial ledger.

Legacy v1 reserved **$2.927505** for 28 runs (20 STT and 8 Brain/TTS)
and 1170 seconds despite 136.264 observed wall seconds. The separate
v2 accounting applies a **clearly labeled historical proxy**:
- unmetered historical Browser Brain+TTS: $0.15 * 8 = $1.20
  (substantially padded, **not known actual tokens or a provider bill**)
- historical STT: measured wall seconds (conservatively >= audio sent)
  times official $0.017/min, with 25% safety margin.
- overall historical v2 estimated cost: **$1.231128**.
- historical previously blocked virtual reservation difference:
  $1.696377. This is **not a refund from OpenAI**.

Under the same original internal $3 local estimate ceiling, v2 now has
$1.768872 available for further reserved operations as of its creation.
The old hard 8-Brain-turn gate is removed *from Browser Lab v2 only*,
not the original legacy/physical ledger.

## New turn accounting

Every call still requires owner REAL consent + a local candidate and
the cloud name check on the first turn (or an existing bounded
in-dialogue followup permit). On one Browser paid operation:
- **Reserve before calling API**: STT at max authorized 20 sec x
  $0.017/min, or Brain+marin at $0.35/90 sec maximum initial hold.
- No parallel paid operations, no money spent from standby, old v1
  remains unchanged.
- On a successful STT, settle using actual PCM seconds sent to
  `gpt-live-transcribe` x official $0.017/min + 25% safety.
- On a successful Brain+marin, a *transparent* A-only
  `Speech.connector` wrapper reads real `response.done.usage`
  input/output text/audio token counters, without changing or storing
  the text, audio, API key, prompts, or response payload.
  Costs follow official `gpt-realtime-2.1-mini` modality and cache rates.
  Existing `gpt-4.1-mini` Chat Completions streaming does **not**
  supply usage; use tiktoken token estimates from original Brain prompt
  and finished text, explicitly marked estimates. Add 25% safety.
  If token reports are absent, charge $0.15 as a safety proxy.
- When API fails/cancels/times out, **retain the whole upfront
  reservation**; do not credit an unknown bill as zero. If provider
  reported token usage unexpectedly exceeds upfront reserve, charge
  observed estimate fully, mark overrun and block future reservations
  if the overall estimate exceeds the $3 guard.

The per-session 600sec Browser Lab timer, finite STT/audio caps,
180-character speech cap, $3 total local estimate cap and 3000sec
total old owner grant are unchanged. Physical HOST-B/COM3/18799 and
production A infrastructure remain unmodified.

Provider invoices may differ: exact historical Chat/TTS usage was not
recorded, and usage records in Chat streaming are estimates. The
authoritative billing remains OpenAI Usage; do not claim the new
$1.231128 local proxy is the actual expense.

## Verify locally on PLAN, without network costs

In PowerShell:

```powershell
cd C:\Users\PLAN\gobot\GoBotHome-host-A
C:\Users\PLAN\gobot\GoBotHome\.venv\Scripts\python.exe -m pytest -q tests/test_host_a_browser_metered_budget.py
```

Browser reset: just refresh `https://plan.tailffc57c.ts.net/`,
choose REAL and consent. It now emits `budget_report` before
audio is sent with the historical/visible revised estimate.
After an actual completed Browser Brain turn, `budget_status` displays
new estimated used/free values. To inspect the local v2 file, read
the JSON in the protected run/ folder. No private transcript, token
or API credential should be committed to GitHub.

Validation on 2026-11-17: 175 selected Python tests pass; JS check
passes; independent connected German Tailscale peer successfully
handshakes HTTPS/WSS and receives `ready`, `journal_status`,
`budget_report` with no API call. Lab /health ready. No new paid
requests were sent in this modification or acceptance testing.
