"""Hardware físico (LEGO SPIKE Prime via BLE) — AINDA NÃO IMPLEMENTADO.

Esta classe existe apenas para que o modo físico possa ser solicitado e falhar de forma clara,
permitindo ativar o simulador. Ela nunca finge estar conectada. A integração real depende do
inventário de peças e de testes com o Hub (veja docs/RELATORIO_TESTES.md).
"""
from backend.errors import HardwareUnavailable
from backend.hardware.base import RobotHardware, SensorReadings

NOT_AVAILABLE = (
    "O modo físico (LEGO SPIKE Prime) ainda não está disponível nesta versão: "
    "falta a integração Bluetooth e o teste com o Hub real. Use o modo simulado."
)


class PhysicalHardware(RobotHardware):
    mode = "physical"

    def connect(self) -> None:
        raise HardwareUnavailable(NOT_AVAILABLE)

    def perform(self, action: str) -> None:
        raise HardwareUnavailable(NOT_AVAILABLE)

    def halt(self) -> None:
        raise HardwareUnavailable(NOT_AVAILABLE)

    def read_sensors(self) -> SensorReadings:
        raise HardwareUnavailable(NOT_AVAILABLE)

    def motor_states(self) -> dict[str, str]:
        raise HardwareUnavailable(NOT_AVAILABLE)
