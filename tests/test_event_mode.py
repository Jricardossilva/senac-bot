"""Prompt 8: verificação de prontidão, modos de hardware e demonstração."""
import pytest
from fastapi.testclient import TestClient

import backend.main as main
from backend.ai.service import ChatService
from backend.config import load_settings
from backend.preflight import build_preflight, check_internet
from tests.fakes import FakeProvider
from tests.kb_helpers import real_kb

client = TestClient(main.app)


def checks_by_id(body: dict) -> dict[str, dict]:
    return {c["id"]: c for c in body["checks"]}


def preflight(monkeypatch, internet: bool, provider: FakeProvider) -> dict:
    monkeypatch.setattr(main, "check_internet", lambda: internet)
    monkeypatch.setattr(main, "chat_service", ChatService(provider, knowledge=real_kb()))
    return client.post("/api/preflight").json()


def test_preflight_all_good(monkeypatch) -> None:
    body = preflight(monkeypatch, True, FakeProvider())
    assert body["ready"] is True
    assert {c["status"] for c in body["checks"]} == {"ok"}
    assert set(checks_by_id(body)) == {"internet", "gemini", "hardware", "knowledge", "emergency"}


def test_preflight_without_internet_warns_and_stays_ready(monkeypatch) -> None:
    provider = FakeProvider()
    body = preflight(monkeypatch, False, provider)
    checks = checks_by_id(body)
    assert checks["internet"]["status"] == "warning"
    assert "respostas locais" in checks["internet"]["message"]
    assert checks["gemini"]["status"] == "warning"
    assert body["ready"] is True
    assert provider.calls == []  # não tenta o Gemini sem internet


@pytest.mark.parametrize(
    "configured,error,expected",
    [(False, None, "GEMINI_API_KEY"), (True, "invalid_key", "aistudio.google.com/apikey"),
     (True, "rate_limited", "cota"), (True, "model_unavailable", "GEMINI_MODEL")],
)
def test_preflight_gemini_messages_are_clear(monkeypatch, configured, error, expected) -> None:
    body = preflight(monkeypatch, True, FakeProvider(configured=configured, error=error))
    gemini = checks_by_id(body)["gemini"]
    assert gemini["status"] == "warning"
    assert expected in gemini["message"] + gemini["action"]
    assert body["ready"] is True


def test_preflight_blocks_when_emergency_is_active(monkeypatch) -> None:
    client.post("/api/emergency")
    body = preflight(monkeypatch, True, FakeProvider())
    assert checks_by_id(body)["emergency"]["status"] == "error"
    assert body["ready"] is False


def test_build_preflight_reports_hardware_failure() -> None:
    body = build_preflight(True, "available", {"hardware_mode": "simulation", "hardware_error": "falhou"})
    hardware = {c["id"]: c for c in body["checks"]}["hardware"]
    assert hardware["status"] == "warning" and "simulador ativo" in hardware["message"]


def test_check_internet_returns_false_when_unreachable() -> None:
    assert check_internet(host="invalid.invalid", timeout=0.5) is False


def test_physical_mode_fails_clearly_and_simulator_stays_active() -> None:
    resp = client.post("/api/hardware/mode", json={"mode": "physical"})
    assert resp.status_code == 409
    assert "simulado" in resp.json()["detail"]
    status = client.get("/api/status").json()
    assert status["hardware_mode"] == "simulation"
    assert status["hardware_error"]
    assert client.post("/api/simulator/action", json={"action": "wave"}).status_code == 200  # simulador segue funcional


def test_activating_simulator_clears_hardware_error() -> None:
    client.post("/api/hardware/mode", json={"mode": "physical"})
    body = client.post("/api/hardware/mode", json={"mode": "simulation"}).json()
    assert body["hardware_error"] is None
    assert "Modo simulado ativado." in body["events"]


def test_invalid_hardware_mode_is_rejected() -> None:
    assert client.post("/api/hardware/mode", json={"mode": "usb"}).status_code == 422


def test_robot_mode_physical_is_accepted_by_config(monkeypatch) -> None:
    monkeypatch.setenv("ROBOT_MODE", "physical")
    assert load_settings().robot_mode == "physical"
    monkeypatch.setenv("ROBOT_MODE", "usb")
    assert load_settings().robot_mode == "simulation"


def test_demo_start_begins_session_and_stop_resets_robot() -> None:
    body = client.post("/api/demo/start").json()
    assert body["demo_active"] is True and body["session_active"] is True
    client.post("/api/simulator/action", json={"action": "wave"})
    client.post("/api/simulator/action", json={"action": "happy"})
    body = client.post("/api/demo/stop").json()
    assert body["demo_active"] is False
    assert body["session_active"] is True  # a sessão continua; só a demonstração termina
    assert (body["expression"], body["simulator_action"]) == ("neutral", "idle")
    assert "Demonstração encerrada." in body["events"]


def test_demo_is_blocked_by_emergency_and_ended_by_it() -> None:
    client.post("/api/demo/start")
    assert client.post("/api/emergency").json()["demo_active"] is False
    assert client.post("/api/demo/start").status_code == 409


def test_ending_the_session_ends_the_demo() -> None:
    client.post("/api/demo/start")
    assert client.post("/api/session/stop").json()["demo_active"] is False


def test_demo_works_without_gemini_or_internet(monkeypatch) -> None:
    """Se a IA falhar, o chat da demonstração segue com respostas locais."""
    monkeypatch.setattr(main, "chat_service", ChatService(FakeProvider(error="unavailable")))
    client.post("/api/demo/start")
    body = client.post("/chat", json={"message": "Quero um desafio"}).json()
    assert body["source"] == "local" and body["response"].startswith("Desafio")
    open_question = client.post("/chat", json={"message": "Explique buracos negros"}).json()
    assert open_question["source"] == "fallback" and open_question["response"]
