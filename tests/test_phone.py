import json
import time
import httpx
import pytest
from fastapi.testclient import TestClient
from gobot.phone import create_phone_app

ORIGIN = "http://192.168.3.15:18785"

def gateway(expires_at=None):
    seen = []
    def upstream(request):
        if request.url.path == "/healthz":
            return httpx.Response(200, json={"status": "ok"})
        assert str(request.url) == "http://127.0.0.1:18781/api/v1/chat/stream"
        body = json.loads(request.content)
        seen.append(body)
        assert body["provider"] == "mock"
        assert body["device_id"] == "phone-demo"
        assert request.headers["Authorization"] == "Bearer fixture-owner-key"
        provider = "bridge:mock" if body["route"] == "agent" else "mock"
        events = [
            {"type": "tool_status", "data": {"debug": "PRIVATE DEBUG"}},
            {"type": "text_delta", "data": {"text": "Привет!"}},
            {"type": "final", "data": {"text": "Привет!", "provider": provider, "secret": "PRIVATE FIELD"}},
        ]
        return httpx.Response(200, text="".join("data: " + json.dumps(event, ensure_ascii=False) + "\n\n" for event in events))
    app = create_phone_app("fixture-owner-key", "192.168.3.15", "192.168.3.0/24",
                           expires_at=expires_at, transport=httpx.MockTransport(upstream), cooldown=0)
    return app, seen

@pytest.mark.parametrize("scenario,route", [("hello", "fast"), ("timer", "fast"), ("bridge", "agent")])
def test_phone_only_fixed_mock_scenarios(scenario, route):
    app, seen = gateway()
    with TestClient(app, base_url=ORIGIN, client=("192.168.3.20", 50000)) as client:
        response = client.get("/api/demo/" + scenario)
        assert response.status_code == 200
        assert "Привет!" in response.text
        assert not any(value in response.text for value in ["fixture-owner-key", "PRIVATE DEBUG", "PRIVATE FIELD"])
        assert seen[-1]["route"] == route
        assert client.get("/api/demo/hello?provider=codex").status_code == 404
        assert client.get("/api/demo/shell").status_code == 404
        assert client.post("/api/demo/hello", json={"text": "arbitrary"}).status_code == 405
        assert client.get("/api/v1/status").status_code == 404

def test_phone_assets_status_and_headers():
    app, _ = gateway()
    with TestClient(app, base_url=ORIGIN, client=("192.168.3.20", 50000)) as client:
        assert "GoBot Home" in client.get("/").text
        assert client.get("/app.js").status_code == 200
        assert client.get("/style.css").status_code == 200
        assert client.get("/keys.json").status_code == 404
        response = client.get("/api/status")
        assert all(item["ok"] for item in response.json()["services"])
        assert response.json()["real_agents_enabled"] is False
        assert response.json()["real_speech_ready"] is False
        assert response.headers["cache-control"] == "no-store"
        assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
        assert response.headers["permissions-policy"] == "camera=(), microphone=(), geolocation=()"

@pytest.mark.parametrize("headers", [
    {"Host": "evil.test"}, {"Origin": "http://evil.test"}, {"Sec-Fetch-Site": "cross-site"},
])
def test_phone_host_origin_boundary(headers):
    app, _ = gateway()
    with TestClient(app, base_url=ORIGIN, client=("192.168.3.20", 50000)) as client:
        assert client.get("/api/demo/hello", headers=headers).status_code == 403

def test_phone_outside_subnet_and_expiry():
    app, _ = gateway()
    with TestClient(app, base_url=ORIGIN, client=("100.90.228.126", 50000)) as client:
        assert client.get("/", headers={"X-Forwarded-For": "192.168.3.20"}).status_code == 403
    app, _ = gateway(expires_at=time.time() - 10)
    with TestClient(app, base_url=ORIGIN, client=("192.168.3.20", 50000)) as client:
        assert client.get("/").status_code == 410

def test_phone_refuses_wildcard_and_loopback_bind():
    for host in ["0.0.0.0", "127.0.0.1", "203.0.113.10"]:
        with pytest.raises(ValueError):
            create_phone_app("fixture", host, "192.168.3.0/24")
