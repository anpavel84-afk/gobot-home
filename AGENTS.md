# GoBot Home boundaries
Work only in this repository. No paid/model calls by default. No firmware flash/OTA/NVS.
Never read, copy or mount CLI credentials. No shell from voice, no global installs, no firewall changes.
Brain, Bridge, voice and image services use 127.0.0.1. The owner's iPhone testing request permits a persistent mock-only phone gateway on the specific Wi-Fi IPv4, restricted to that subnet, until stopped. No firewall/router changes, credentials, history access, arbitrary proxy, CLI or shell through this HTTP gateway. The separate private Tailscale HTTPS gateway uses exact peer, Host and Origin allowlists and may proxy validated product requests to Brain and save an OpenAI key through Windows DPAPI. Real CLI admission requires matching offline isolation evidence, no model tools, and explicit quota consent; no tests may spend quota without the owner's permission.
Tests use mocks; preserve upstream SHAs and regression-test every patch. Do not claim mock audio is speech.
Gemini CLI live execution is retired. Google routing uses official project-local Antigravity (agy),
strict per-session deny rules for files/commands/web/MCP, project child home and matching native audit.
OWNER DIRECT 2026-11-10 supersedes the CLI-only everyday conversation rule:
native gpt-realtime-2.1-mini is the target primary conversation engine (marin unless configured otherwise).
Browser uses audio-only WebRTC and authenticated server sideband controls. Brain owns ACL, tools,
context, visual scenes, budgets and confirmed expert jobs. No provider credentials/data channel in browser.
Do not enable it by default before acceptance; keep explicit legacy STT/CLI/TTS rollback.
Antigravity/Codex remain optional confirmed experts. Ordinary Realtime turns must not invoke legacy
STT, Speech Formatter, separate TTS or CLI. No GPT-Live migration or silent model/voice fallback.
Legacy AUTO/FAST use registered Antigravity Flash only. Unavailability must not trigger a
heavy agent or mock. Expensive fallback requires explicit per-request approval.
OpenAI STT and TTS remain primary for legacy. Whisper and Denis are explicit manual offline choices only.
OpenAI paid speech tests require separate owner permission; CLI quota consent does not cover API charges.
Realtime developer trials require a new scoped budget; old speech/phone/opening budgets cannot be reused.
OWNER DIRECT 2026-11-10 now authorizes ongoing manual Realtime testing on the owner phone:
owner_interactive may have no session/response/time/usage cap or expiry, bound to that client.
Do not keep asking to renew each manual trial. This does not authorize automated paid developer
runs, experts or image generation. Keep consent, usage accounting, Stop, idle/pagehide cleanup and ACL.
Keep all 100 cached openings for legacy; disable them for native Realtime conversation.
Speaker embeddings stay local, encrypted with Windows DPAPI; no raw enrollment recordings on disk.
Product source: docs/GOBOT_HOME_TARGET_SYSTEM.md v0.2 (96e0f3d), still a draft beyond owner-approved corrections.
Current priority is M1 telemetry and measured latency. Feedback never counts as useful-answer TTFA.
Real profiling requires explicit remaining owner budget; historical latency evidence stays unchanged.
Family/personal/guest scopes must not cross. Voice identity alone cannot grant personal-history access;
uncertain voice/pending recognition downgrades to guest, except a short utterance in a PIN-confirmed session.
OWNER DIRECT Family Identity amendment: a PIN phone session is not proof of the speaker on each turn.
Native WebRTC passes an opt-in local SpeakerIdentity mirror; keep candidate context guest/RAM only, including
followup. Never preload a PIN owner's private archive as a latency optimization. Voice matches alone do
not authorize private retrieval. Profile/epoch/speaker-rights changes invalidate provider history and jobs;
recreate the session rather than editing user_id in the prompt. No second family-profile database.
Native SpeakerIdentity uses a bounded local PCM mirror into the existing opt-in ECAPA worker.
No embeddings to providers, raw recordings to disk, or guessed enrollment/calibration. Known voice
does not authorize memory. Family preferences are versioned against existing profile_id; free-form
personalization stays user-level data, not a privileged instruction. Child editing is denied without
an established parental grant. Preserve legacy SpeechFormatter/audio and demo A before deployment;
demo2 A/B shares one Brain, and the local full backup is never published.

After every meaningful implementation, update docs/CURRENT_STATUS.md as the single factual project passport. Link changed code and evidence, record limitations and deployment state, and distinguish planned/mock/provider/browser/iPhone/hardware validation. Keep GOBOT_HOME_TARGET_SYSTEM.md as the requirements authority; do not create another competing status document.

Separate native input transcription is asynchronous guidance, not proof of what the audio model understood.
Keep native audio fast; explicit user-confirmed text correction reuses the same session.
Subject-frame warnings must not launch automatic paid repairs or be called universal semantic verification.
Protect short accidental face taps from cancelling playing audio; Stop remains immediate.

OWNER DIRECT two-stage visuals supersedes always-avatar-until-answer confirmation:
show explicitly provisional question-topic scenes, then bounded answer-aligned refinements.
Reuse VisualService/ImageCache and existing scoped visual memory. No new classifier LLM.
Unknown alignment preserves provisional/neutral; mismatches deny refined media/generation.
Native two-stage uses Wikimedia-first -> separately consented generation-if-missing;
Implicit provisional paid generation waits for stable alignment. Never infer new ImageGen permission.
Explicit public image requests join the same visual worker; Wikimedia first, then only already
consented/budgeted generation. Auto accompaniment OFF is not an explicit-action ban.
Topic recognition/badges are not image fulfillment. Publish a real asset or a recoverable,
specific source/policy/consent/limit failure card; decoded client-presented differs from scene_sent.

Expert handoff v2: one processed user confirmation authorizes at most one CLI job.
Separate finite client/profile/expiry/count grant and confirmed adult Family epoch are required.
The original expert_start call receives accepted exactly once; completion is a separate
user-level data notice, not a second function_call_output or an instruction from the expert.
New questions retain permitted result cards without stale voice interruption; remember=false
stays RAM-only. Profile change/revocation/close never transfers results or auto-retries jobs.
Catalog metadata and offline isolation are not real entitlement, latency or iPhone acceptance.
Blocked expert admission must not become an awaiting-confirmation job. Expose effective admission
to Realtime instructions and the existing expert panel; only accepted=true means submitted.
Persist allowlisted stage/rejection counters only, never household transcripts for diagnostics.
Owner requested A restored for manual comparison: isolate its browser settings/consents from B,
preserve frozen baseline bytes and Russian formatter; opening A must not invoke STT/CLI/TTS.
Any bound manual-consent bootstrap applies once and respects subsequent local revocation.
This does not authorize automated paid tests or enable B expert jobs.

OWNER DIRECT 2026-11-11 separately permits OpenAI Image API fallback on the existing
bound owner phone: at most 20 attempts per UTC day, 1024x1024 low quality/complexity,
Wikimedia first, no automatic retries. This does not permit paid developer trials,
global profile activation, CLI calls or unsafe Codex image tools. Enforce the server cap
as well as profile consent; keep raw credentials and household settings out of Git/logs.
