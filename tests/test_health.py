from fastapi.testclient import TestClient

from backend.ai.service import ChatService
from backend.main import app
from tests.fakes import FakeProvider

client = TestClient(app)


def _service(configured: bool = False) -> ChatService:
    return ChatService(FakeProvider(configured=configured))


def test_health_reports_gemini_not_configured(monkeypatch) -> None:
    monkeypatch.setattr("backend.main.chat_service", _service(configured=False))
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["ai_status"] == "not_configured"
    assert body["gemini_status"] == "not_configured"
    assert body["gemini_configurado"] is False


def test_homepage_is_available() -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    assert "SENAC BOT" in resp.text
    assert "Senac Paraíba" in resp.text
    assert 'id="visitor-ai-status"' not in resp.text


def test_frontend_assets_are_available() -> None:
    css = client.get("/assets/app.css")
    js = client.get("/assets/app.js")
    assert css.status_code == 200
    assert ".robot-svg" in css.text
    assert js.status_code == 200
    assert "/api/simulator/action" in js.text


def test_chat_uses_local_replies_without_gemini(monkeypatch) -> None:
    monkeypatch.setattr("backend.main.chat_service", _service(configured=False))
    resp = client.post("/chat", json={"message": "Oi"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "local"
    assert body["response"].startswith("Olá!")


def test_chat_falls_back_when_gemini_is_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(
        "backend.main.chat_service", ChatService(FakeProvider(error="unavailable"))
    )
    body = client.post("/chat", json={"message": "Explique buracos negros"}).json()
    assert body["source"] == "fallback"
    assert body["reason"] == "unavailable"
    assert body["response"]


def test_chat_uses_gemini_when_configured(monkeypatch) -> None:
    monkeypatch.setattr("backend.main.chat_service", ChatService(FakeProvider()))
    body = client.post("/chat", json={"message": "Explique buracos negros", "session_id": "t"}).json()
    assert (body["source"], body["response"]) == ("gemini", "Resposta do Gemini.")


def test_ai_check_endpoint(monkeypatch) -> None:
    monkeypatch.setattr("backend.main.chat_service", ChatService(FakeProvider()))
    assert client.post("/api/ai/check").json()["ai_status"] == "available"


def test_chat_rejects_empty_message() -> None:
    resp = client.post("/chat", json={"message": "   "})
    assert resp.status_code == 422


def test_operator_controls_and_emergency_stop() -> None:
    started = client.post("/api/session/start")
    assert started.status_code == 200
    assert started.json()["session_active"] is True

    stopped = client.post("/api/emergency")
    assert stopped.status_code == 200
    assert stopped.json()["emergency_stop"] is True
    assert stopped.json()["session_active"] is False
    assert client.post("/api/simulator/action", json={"action": "wave"}).status_code == 409
    assert client.post("/api/session/start").status_code == 409

    released = client.post("/api/emergency")
    assert released.status_code == 200
    assert released.json()["emergency_stop"] is False


def test_simulator_actions_are_allowlisted() -> None:
    resp = client.post("/api/simulator/action", json={"action": "wave"})
    assert resp.status_code == 200
    assert resp.json()["simulator_action"] == "wave"
    assert resp.json()["robot_state"] == "Cumprimentando"
    assert client.post("/api/simulator/action", json={"action": "drive"}).status_code == 422


def test_status_reports_hardware_mode_simulation() -> None:
    body = client.get("/api/status").json()
    assert body["hardware_mode"] == "simulation"
    assert body["ai_status"] in ("configured", "not_configured")
    assert isinstance(body["events"], list)


def test_stop_session_and_events_are_recorded() -> None:
    client.post("/api/session/start")
    body = client.post("/api/session/stop").json()
    assert body["session_active"] is False
    assert body["robot_state"] == "Offline"
    assert "Sessão encerrada." in body["events"]


def test_controller_rejects_unlisted_action() -> None:
    from backend.errors import RobotError
    from backend.main import controller

    try:
        controller.execute("drive")
    except RobotError:
        return
    raise AssertionError("ação fora da lista permitida deveria ser recusada")


def test_unexpected_error_is_handled_centrally(monkeypatch) -> None:
    def boom(_: str) -> str:
        raise RuntimeError("falha")

    monkeypatch.setattr(
        "backend.main.chat_service", type("S", (), {"reply": staticmethod(lambda *_: boom(""))})()
    )
    resp = TestClient(app, raise_server_exceptions=False).post("/chat", json={"message": "oi"})
    assert resp.status_code == 500
    assert "detail" in resp.json()


def test_settings_defaults_and_invalid_robot_mode(monkeypatch) -> None:
    from backend.config import load_settings

    monkeypatch.setenv("ROBOT_MODE", "usb")
    monkeypatch.setenv("SENAC_PORT", "abc")
    monkeypatch.delenv("APP_ENV", raising=False)
    s = load_settings()
    assert s.robot_mode == "simulation"
    assert s.port == 8000
    assert s.app_env == "development"


def test_fullscreen_control_exists_in_frontend() -> None:
    assert 'id="fullscreen-button"' in client.get("/").text
    assert "requestFullscreen" in client.get("/assets/app.js").text
