"""Temporary LAN demonstration gateway. No owner credentials or general proxy in its API."""
import asyncio
import ipaddress
import json
import re
import time
from pathlib import Path
from uuid import uuid4

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

ROOT = Path(__file__).resolve().parents[3]
SCENARIOS = {
    "hello": ("Привет, GoBot", "fast"),
    "timer": ("Поставь таймер на пять минут", "fast"),
    "bridge": ("Проверь тестовую текстовую задачу", "agent"),
}
ASSETS = {"": ("index.html", "text/html"), "app.js": ("app.js", "text/javascript"),
          "style.css": ("style.css", "text/css")}


def create_phone_app(api_token, host, network, port=18785, expires_at=None,
                     transport=None, cooldown=1):
    address = ipaddress.ip_address(host)
    subnet = ipaddress.ip_network(network, strict=False)
    if address.version != 4 or not address.is_private or address.is_loopback or address not in subnet:
        raise ValueError("A specific private Wi-Fi IPv4 is required")
    origin = "http://" + host + ":" + str(port)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    active = asyncio.Semaphore(2)
    recent = {}
    request_count = 0

    @app.middleware("http")
    async def boundary(request: Request, call_next):
        try:
            peer = ipaddress.ip_address(request.client.host)
            valid_peer = peer in subnet or peer.is_loopback
        except (ValueError, AttributeError):
            valid_peer = False
        if not valid_peer:
            return JSONResponse({"error": "Wi-Fi subnet only"}, status_code=403)
        if request.headers.get("host") != host + ":" + str(port):
            return JSONResponse({"error": "Host denied"}, status_code=403)
        if request.headers.get("origin") not in {None, origin} or request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse({"error": "Origin denied"}, status_code=403)
        if expires_at is not None and time.time() >= expires_at:
            return JSONResponse({"error": "Phone demo expired"}, status_code=410)
        if request.method != "GET":
            return JSONResponse({"error": "Read-only demo interface"}, status_code=405)
        response = await call_next(request)
        response.headers.update({
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "X-Frame-Options": "DENY",
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
            "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
        })
        return response

    @app.get("/api/status")
    async def status():
        checks = []
        async with httpx.AsyncClient(transport=transport, trust_env=False, timeout=2) as client:
            for name, target_port in [("Brain", 18781), ("Bridge · mock", 18782),
                                      ("Голосовой mock-стенд", 18783), ("Изображения", 18784)]:
                try:
                    result = await client.get("http://127.0.0.1:" + str(target_port) + "/healthz")
                    ok = result.status_code == 200
                except httpx.HTTPError:
                    ok = False
                checks.append({"name": name, "ok": ok})
        test_file = ROOT / "docs/tests-output.txt"
        match = re.search(r"(\d+) passed", test_file.read_text(encoding="utf-8")) if test_file.exists() else None
        return {"mode": "mock-only", "services": checks, "unit_tests_passed": int(match[1]) if match else None,
                "remaining_seconds": max(0, int(expires_at - time.time())) if expires_at is not None else None,
                "real_speech_ready": False, "real_agents_enabled": False}

    @app.get("/api/demo/{scenario}")
    async def demo(scenario: str, request: Request):
        nonlocal request_count
        if scenario not in SCENARIOS or request.query_params:
            raise HTTPException(404, "Only fixed mock demonstrations are available")
        peer = request.client.host
        now = time.monotonic()
        if now - recent.get(peer, -1000) < cooldown:
            raise HTTPException(429, "Demo rate limit")
        try:
            await asyncio.wait_for(active.acquire(), .1)
        except TimeoutError:
            raise HTTPException(429, "Demo busy")
        request_count += 1
        recent[peer] = now
        text, route = SCENARIOS[scenario]
        expected = "bridge:mock" if route == "agent" else "mock"
        body = {"text": text, "route": route, "provider": "mock", "device_id": "phone-demo",
                "conversation_id": str(uuid4()), "turn_id": str(uuid4())}

        async def generate():
            try:
                async with asyncio.timeout(15):
                    async with httpx.AsyncClient(transport=transport, trust_env=False, timeout=12) as client:
                        async with client.stream(
                            "POST", "http://127.0.0.1:18781/api/v1/chat/stream",
                            headers={"Authorization": "Bearer " + api_token}, json=body
                        ) as response:
                            response.raise_for_status()
                            async for line in response.aiter_lines():
                                if not line.startswith("data: "):
                                    continue
                                item = json.loads(line[6:])
                                kind, data = item.get("type"), item.get("data", {})
                                payload = {}
                                if kind in {"text_delta", "sentence_ready"}:
                                    payload = {"text": str(data.get("text", ""))[:32000]}
                                elif kind == "widget_command":
                                    payload = {"command": {"type": "custom", "payload": {
                                        "namespace": "gobot.ui", "version": 1, "command": "timer.start",
                                        "duration_ms": 300000}}}
                                elif kind == "final":
                                    if data.get("provider") != expected:
                                        raise ValueError("Mock route verification failed")
                                    payload = {"text": str(data.get("text", ""))[:32000],
                                               "provider": expected, "mock": True}
                                elif kind in {"error", "cancelled"}:
                                    payload = {"code": "demo_interrupted"}
                                else:
                                    continue
                                yield "data: " + json.dumps({"type": kind, "data": payload}, ensure_ascii=False) + "\n\n"
            except (httpx.HTTPError, TimeoutError, ValueError):
                yield 'data: {"type":"error","data":{"code":"demo_unavailable"}}\n\n'
            finally:
                active.release()
        return StreamingResponse(generate(), media_type="text/event-stream")

    @app.get("/")
    async def index():
        return FileResponse(ROOT / "services/phone/dist/index.html", media_type="text/html")

    @app.get("/{asset}")
    async def static(asset: str):
        if asset not in ASSETS or not asset:
            raise HTTPException(404)
        filename, mime = ASSETS[asset]
        return FileResponse(ROOT / "services/phone/dist" / filename, media_type=mime)

    return app
