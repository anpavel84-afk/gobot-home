"""Offline isolation checks. Codex sends to an in-process mock HTTP provider only."""
import asyncio
import json
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services/brain"))
from gobot.live_agents import CodexLiveAdapter, codex_binary, digest, policy_digest, codex_account_present

async def audit_codex():
    calls = []
    async def handler(reader, writer):
        try:
            header = await reader.readuntil(b"\r\n\r\n")
            length = 0
            for line in header.split(b"\r\n"):
                if line.lower().startswith(b"content-length:"):
                    length = int(line.split(b":", 1)[1])
            body = await reader.readexactly(length) if length else b"{}"
            # Never record request headers or tokens.
            if body[:2] == b"\x1f\x8b":
                import gzip
                body = gzip.decompress(body)
            try:
                item = json.loads(body)
                tools = item.get("tools", [])
                calls.append({"tools": [tool.get("name", tool.get("type", "unknown")) for tool in tools]})
            except ValueError:
                calls.append({"parse_error": True})
            data = b'{"error":{"message":"GoBot offline isolation audit complete","type":"audit_complete"}}'
            writer.write(b"HTTP/1.1 400 Bad Request\r\nContent-Type: application/json\r\nConnection: close\r\nContent-Length: " + str(len(data)).encode() + b"\r\n\r\n" + data)
            await writer.drain()
        finally:
            writer.close()
    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    extra = {
        "model_provider": "gobot_offline",
        "model_providers": {"gobot_offline": {
            "name": "GoBot offline audit fixture", "base_url": "http://127.0.0.1:" + str(port) + "/v1",
            "wire_api": "responses", "requires_openai_auth": False,
            "request_max_retries": 0, "stream_max_retries": 0,
        }},
    }
    try:
        async with asyncio.timeout(30):
            try:
                async for _ in CodexLiveAdapter().stream("Offline fixture probe. No tools.", {}, extra_config=extra):
                    pass
            except Exception as error:
                failure = type(error).__name__
    except TimeoutError:
        failure = "TimeoutError"
    finally:
        server.close()
        await server.wait_closed()
    tools = calls[-1].get("tools") if calls else None
    report = {"artifact_sha256": digest(codex_binary()), "tools": tools, "mock_http_requests": len(calls),
              "policy_sha256": policy_digest(), "oauth_authenticated": await codex_account_present(),
              "real_model_requests": 0, "probe_terminal": failure,
              "isolated": bool(calls) and all(call.get("tools") == [] for call in calls)}
    if not report["isolated"]:
        report.pop("tools", None)  # Missing evidence fails admission.
    path = ROOT / "run/agent-isolation.json"
    result = json.loads(path.read_text()) if path.exists() else {}
    result["codex"] = report
    path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"codex_offline_audit": report}, indent=2))

if __name__ == "__main__":
    asyncio.run(audit_codex())
