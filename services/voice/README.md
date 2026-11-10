# Pinned upstream voice integration
Source vendor/xiaozhi-server/main/xiaozhi-server at docs/dependencies.lock.json SHA.
The real interface is core.providers.llm.base.LLMProviderBase.response(session_id, dialogue).
Provider overlay lives in providers/llm/gobot/gobot.py; the supported factory discovers directories
core/providers/llm/<type>/<type>.py. ASR and TTS interfaces remain upstream.
`python scripts/prepare_upstream.py` verifies SHA, checks/applies a separate security patch and writes
ONLY vendor source overlay and ignored data/.config.yaml. It does not launch upstream or install Torch.
The initial profile is deliberately unlaunchable without explicit ASR/TTS/model provisioning. No plugin,
MCP endpoint, shared demo credentials, Java, Vue, MySQL or Redis is enabled by our config.
WS v1 is the initial production target; v2/v3 test codec coverage does not prove upstream interoperation.
Do not enable LAN before strict device provisioning, token verification, safe logs and permission review.

The generated base config is sanitized from the pinned original using git show. Empty nested mappings
alone are insufficient because upstream recursively merges config; inherited demo providers and plugin
credentials are removed before writing data/.config.yaml. No sanitized or secret runtime config is committed.
Guarded `gobot_openai_ru` providers use upstream ASR artifacts / TTS WAV interfaces and async HTTP.
They are segment-based ASR and sentence-based WAV TTS, not a verified true streaming audio backend.
