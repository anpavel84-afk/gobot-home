# HOST-A Browser Voice Lab — owner-authorized local full text journal

Owner approval: 2026-11-17, ChatGPT GoBot conversation. Applies only to
experimental Browser Voice Lab started on PLAN. Not to Spotpear firmware,
HOST-B, Telegram, or production chat archival.

## Private local files

- Conversations (one JSONL per Browser Voice Lab session):
  `run/host-a/browser-lab/conversations/session-*.jsonl`
- Existing numeric-only historical latency events:
  `run/host-a/browser-lab/latency_events.jsonl`

Files are in the PLAN user's Windows profile under the A worktree. They are
not served by FastAPI, Tailscale Serve, or GitHub. The `run/` directory must
remain excluded from Git. No raw PCM/Opus, audio files, API keys or request
authorization headers are saved.

The browser displays the new session file name once the WebSocket connects.
The mobile frontend may need a refresh after server code updates.

## Events and interpretation

Each JSONL line includes UTC timestamp, local session ID, turn number,
stage and relative milliseconds. This includes real Vosk changing partial
hypotheses (including background speech), final Vosk, local wake candidate,
OpenAI STT partial deltas/final, cloud verification, exact user question handed
to existing Brain, Brain textual deltas/sentences/final answer and routing,
TTS audio start, final playback confirmation, errors and budget metadata.

`turn_analysis` groups the recorded texts with duration breakdowns.
An occurrence of `модников` or `маньяка` in Vosk text does NOT prove that
the owner pronounced the exact word or that the candidate woke the system.
Only independently verified `wake` and `cloud_verdict` events establish that.

A missing `session_end`, a `complete=false` footer or the browser
`FULL_TEXT_JOURNAL_INCOMPLETE` event means an incomplete capture.

## Reading journals locally on PLAN

From PowerShell:

```powershell
cd C:\Users\PLAN\gobot\GoBotHome-host-A
C:\Users\PLAN\gobot\GoBotHome\.venv\Scripts\python.exe tools\host_a_analyze_conversations.py --last 3
```

For a report that prints timings and classifications without conversation text,
add `--no-text`.

## Data handling

The owner explicitly approved saving spoken text during this lab. Avoid
syncing or publishing the private files to GitHub or third-party storage.
Old experiments before full-text logging are not retroactively recoverable.
Storage has a finite 24 MiB per-session bound; if exceeded, completeness is
marked false rather than silently losing part of the log.

The shared financial guard is not affected by turning on local text logging.
Spotpear remains allocated to HOST-B.
