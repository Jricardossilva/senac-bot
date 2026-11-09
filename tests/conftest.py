"""Isola o estado global do robô entre os testes."""
import pytest

import backend.main as main
from backend.events import EventManager
from backend.hardware.simulator import SimulatedHardware
from backend.robot.controller import RobotController
from backend.state import StateManager


@pytest.fixture(autouse=True)
def fresh_robot(monkeypatch):
    events = EventManager()
    hardware = SimulatedHardware()
    controller = RobotController(hardware, StateManager(), events)
    monkeypatch.setattr(main, "events", events)
    monkeypatch.setattr(main, "controller", controller)
    return controller
