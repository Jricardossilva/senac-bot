"""Gerenciador de estados da aplicação e do robô."""
from dataclasses import dataclass
from threading import RLock


@dataclass
class RuntimeState:
    session_active: bool = False
    emergency_stop: bool = False
    robot_state: str = "Aguardando"
    simulator_action: str = "idle"  # movimento atual
    expression: str = "neutral"
    movement_started: float = 0.0
    demo_active: bool = False


class StateManager:
    """Guarda o estado em memória; o lock é reentrante para uso pelo controlador."""

    def __init__(self) -> None:
        self.lock = RLock()
        self._state = RuntimeState()

    @property
    def state(self) -> RuntimeState:
        return self._state
