# GoBot Home boundaries
Work only in this repository. No paid/model calls by default. No firmware flash/OTA/NVS.
Never read, copy or mount CLI credentials. No shell from voice, no global installs, no firewall changes.
Brain, Bridge, voice and image services use 127.0.0.1. The owner's iPhone testing request permits a persistent mock-only phone gateway on the specific Wi-Fi IPv4, restricted to that subnet, until stopped. No firewall/router changes, credentials, history access, arbitrary proxy, CLI or shell through this HTTP gateway. The separate private Tailscale HTTPS gateway uses exact peer, Host and Origin allowlists and may proxy validated product requests to Brain and save an OpenAI key through Windows DPAPI. Real CLI admission requires matching offline isolation evidence, no model tools, and explicit quota consent; no tests may spend quota without the owner's permission.
Tests use mocks; preserve upstream SHAs and regression-test every patch. Do not claim mock audio is speech.
Gemini CLI live execution is retired. Google routing uses official project-local Antigravity (agy),
strict per-session deny rules for files/commands/web/MCP, project child home and matching native audit.
AUTO/FAST use registered Antigravity Flash only. Unavailability must not trigger a
heavy agent or mock. Expensive fallback requires explicit per-request approval.
OpenAI STT and TTS are primary. Whisper and Denis are explicit manual offline choices only.
OpenAI paid speech tests require separate owner permission; CLI quota consent does not cover API charges.
Speaker embeddings stay local, encrypted with Windows DPAPI; no raw enrollment recordings on disk.
Family/personal/guest scopes must not cross. Voice identity alone cannot grant personal-history access;
uncertain voice/pending recognition downgrades to guest, except a short utterance in a PIN-confirmed session.
