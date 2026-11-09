import pytest
from fastapi.testclient import TestClient

import backend.main as main
from backend.ai.service import ChatService
from backend.events import EventManager
from backend.hardware.simulator import SimulatedHardware
from backend.robot.actions import EXPRESSIONS, GESTURE_SECONDS, MOVEMENTS
from backend.robot.controller import RobotController
from backend.state import StateManager
from tests.fakes import FakeProvider

client = TestClient(main.app)


def act(action: str, origin: str = "operator"):
    return client.post("/api/simulator/action", json={"action": action, "origin": origin})


def sensors(**values):
    return client.post("/api/simulator/sensors", json=values)


def test_spec_lists_are_complete() -> None:
    assert set(EXPRESSIONS) == {
        "neutral", "happy", "curious", "thinking", "speaking", "surprised", "sad", "disconnected",
    }
    required = {
        "look_left", "look_right", "tilt_head", "left_arm", "right_arm", "wave",
        "celebrate", "wheels_forward", "wheels_backward", "spin", "stop",
    }
    assert required <= set(MOVEMENTS)


@pytest.mark.parametrize("action", sorted(set(EXPRESSIONS) - {"disconnected"}) + sorted(MOVEMENTS))
def test_every_allowed_action_is_accepted(action: str) -> None:
    resp = act(action)
    assert resp.status_code == 200
    body = resp.json()
    assert action in (body["expression"], body["simulator_action"])


def test_unlisted_action_is_rejected() -> None:
    assert act("fire_laser").status_code == 422
    assert act("").status_code == 422


def test_movement_and_expression_are_independent() -> None:
    act("happy")
    body = act("wave").json()
    assert (body["expression"], body["simulator_action"]) == ("happy", "wave")
    assert body["motors"]["right_arm"] == "moving"


def test_gesture_returns_to_idle_but_wheels_persist() -> None:
    now = [100.0]
    controller = RobotController(SimulatedHardware(), StateManager(), EventManager(), clock=lambda: now[0])
    controller.execute("wave")
    now[0] += GESTURE_SECONDS - 0.1
    assert controller.snapshot()["simulator_action"] == "wave"
    now[0] += 0.2
    assert controller.snapshot()["simulator_action"] == "idle"
    controller.execute("wheels_backward")
    now[0] += 60
    assert controller.snapshot()["simulator_action"] == "wheels_backward"


def test_sensor_snapshot_and_derived_values() -> None:
    body = sensors(distance_cm=35).json()
    assert body["sensors"] == {"distance_cm": 35, "proximity": "near", "obstacle": False, "connected": True}
    body = sensors(distance_cm=10).json()
    assert body["sensors"]["obstacle"] is True
    assert sensors(distance_cm=500).status_code == 422
    assert sensors(distance_cm=-1).status_code == 422


def test_obstacle_blocks_forward_but_not_backward() -> None:
    sensors(distance_cm=10)
    blocked = act("wheels_forward")
    assert blocked.status_code == 409
    assert "Obstáculo" in blocked.json()["detail"]
    assert act("wheels_backward").status_code == 200


def test_obstacle_appearing_while_moving_stops_wheels() -> None:
    sensors(distance_cm=150)
    assert act("wheels_forward").json()["motors"]["wheels"] == "forward"
    body = sensors(distance_cm=5).json()
    assert body["motors"]["wheels"] == "stopped"
    assert body["simulator_action"] == "stop"
    assert body["expression"] == "surprised"
    assert "Obstáculo detectado: rodas paradas." in body["events"]


def test_disconnection_halts_and_blocks_commands() -> None:
    act("wheels_forward")
    body = sensors(connected=False).json()
    assert body["expression"] == "disconnected"
    assert body["motors"]["wheels"] == "stopped"
    assert act("wave").status_code == 409
    assert act("stop").status_code == 200
    assert sensors(connected=True).json()["expression"] == "neutral"
    assert act("wave").status_code == 200


def test_emergency_stop_blocks_every_command() -> None:
    client.post("/api/emergency")
    for action in ("wave", "wheels_forward", "happy", "stop"):
        assert act(action).status_code == 409
    assert client.post("/chat", json={"message": "oi"}).status_code == 409
    body = client.post("/api/emergency").json()
    assert body["emergency_stop"] is False
    assert act("wave").status_code == 200


def test_chat_reaction_goes_through_controller(monkeypatch) -> None:
    monkeypatch.setattr(main, "chat_service", ChatService(FakeProvider(configured=False)))
    body = client.post("/chat", json={"message": "Olá"}).json()
    assert body["intent"] == "greeting"
    status = client.get("/api/status").json()
    assert (status["expression"], status["simulator_action"]) == ("happy", "wave")


def test_chat_reaction_for_open_question_is_curious(monkeypatch) -> None:
    monkeypatch.setattr(main, "chat_service", ChatService(FakeProvider()))
    client.post("/chat", json={"message": "Explique buracos negros"})
    assert client.get("/api/status").json()["expression"] == "curious"


def test_conversation_origin_does_not_flood_operator_events() -> None:
    act("thinking", origin="conversation")
    act("speaking", origin="conversation")
    assert client.get("/api/status").json()["events"] == []
    act("happy")
    assert client.get("/api/status").json()["events"] == ["Expressão: feliz."]


def test_ai_layer_cannot_reach_the_controller() -> None:
    """A IA só devolve texto/intenção: nenhum módulo de backend/ai importa o controlador ou o hardware."""
    from pathlib import Path

    for path in Path("backend/ai").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "backend.robot" not in text, path
        assert "backend.hardware" not in text, path


def test_status_websocket_pushes_changes() -> None:
    with client.websocket_connect("/ws/status") as ws:
        first = ws.receive_json()
        assert first["application"] == "online"
        assert first["expression"] == "neutral"
        act("happy")
        update = ws.receive_json()
        assert update["expression"] == "happy"
