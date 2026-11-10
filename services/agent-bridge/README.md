# Host Agent Bridge
Implementation: `services/brain/gobot/bridge.py`, parsers: `gobot/agents.py`.
Run `python scripts/manage.py start`. Requests: signed POST /v1/stream with timestamp and one-use nonce.
Response: NDJSON signed per sequence and request nonce. HMAC authentication works in both directions.
Only mock/auto are admitted; CLI execution is technically blocked. Installed read-only CLI flags alone
have not proven denial of host shell, foreign-file reads and configured MCP tools on this Windows host.
No credentials are copied. Real model usage requires separate owner permission plus containment validation.
`agent.exe` is Grok here, NOT Cursor. Cursor is `cursor-agent.cmd`; shell shims cannot carry voice prompts.
