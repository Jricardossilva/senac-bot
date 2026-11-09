"""Interface comum de hardware, implementada pelo simulador e (no futuro) pelo LEGO SPIKE Prime."""
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class SensorReadings:
    distance_cm: int
    connected: bool


class RobotHardware(ABC):
    mode: str

    @abstractmethod
    def perform(self, action: str) -> None:
        """Executa uma ação (movimento ou expressão) já validada pelo controlador."""

    @abstractmethod
    def halt(self) -> None:
        """Interrompe imediatamente qualquer movimento."""

    @abstractmethod
    def read_sensors(self) -> SensorReadings:
        """Lê os sensores (distância frontal e conexão)."""

    @abstractmethod
    def motor_states(self) -> dict[str, str]:
        """Estado atual dos motores/articulações."""
