"""Hardware simulado: mantém ações e sensores em memória; a animação ocorre no navegador."""
from backend.hardware.base import RobotHardware, SensorReadings
from backend.robot.actions import EXPRESSIONS

MAX_DISTANCE_CM = 200
DEFAULT_DISTANCE_CM = 150


class SimulatedHardware(RobotHardware):
    mode = "simulation"

    def __init__(self) -> None:
        self.movement = "idle"
        self.expression = "neutral"
        self._distance_cm = DEFAULT_DISTANCE_CM
        self._connected = True

    def perform(self, action: str) -> None:
        if action in EXPRESSIONS:
            self.expression = action
        else:
            self.movement = action

    def halt(self) -> None:
        self.movement = "stop"

    def read_sensors(self) -> SensorReadings:
        return SensorReadings(distance_cm=self._distance_cm, connected=self._connected)

    def motor_states(self) -> dict[str, str]:
        move = self.movement
        return {
            "head": {"look_left": "left", "look_right": "right", "tilt_head": "tilted"}.get(move, "centered"),
            "left_arm": "moving" if move in ("left_arm", "celebrate") else "stopped",
            "right_arm": "moving" if move in ("right_arm", "wave", "celebrate") else "stopped",
            "wheels": {"wheels_forward": "forward", "wheels_backward": "backward", "spin": "turning"}.get(
                move, "stopped"
            ),
        }

    # --- apenas simulador: valores editáveis pelo operador ---
    def set_distance(self, distance_cm: int) -> None:
        self._distance_cm = max(0, min(MAX_DISTANCE_CM, int(distance_cm)))

    def set_connected(self, connected: bool) -> None:
        self._connected = connected
