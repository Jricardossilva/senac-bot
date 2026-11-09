"""Controlador do robô: único ponto que executa ações, aplicando lista permitida e regras de segurança."""
import logging
import time
from collections.abc import Callable

from backend.errors import EmergencyStopActive, HardwareUnavailable, RobotError
from backend.events import EventManager
from backend.hardware.base import RobotHardware
from backend.hardware.physical import PhysicalHardware
from backend.hardware.simulator import SimulatedHardware
from backend.robot.actions import (
    ALLOWED_ACTIONS,
    DEFAULT_REACTION,
    EXPRESSIONS,
    GESTURE_SECONDS,
    MOMENTARY_MOVEMENTS,
    MOVEMENTS,
    NEAR_CM,
    OBSTACLE_CM,
    REACTIONS,
)
from backend.state import StateManager

logger = logging.getLogger("senac_bot.controller")


class RobotController:
    def __init__(
        self,
        hardware: RobotHardware,
        state: StateManager,
        events: EventManager,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._hardware = hardware
        self._state = state
        self._events = events
        self._clock = clock
        self.hardware_error: str | None = None

    # ---------- leitura ----------
    def snapshot(self) -> dict[str, object]:
        with self._state.lock:
            self._expire_gesture()
            s = self._state.state
            sensors = self._hardware.read_sensors()
            return {
                "session_active": s.session_active,
                "emergency_stop": s.emergency_stop,
                "robot_state": s.robot_state,
                "simulator_action": s.simulator_action,
                "expression": s.expression,
                "hardware_mode": self._hardware.mode,
                "hardware_error": self.hardware_error,
                "demo_active": s.demo_active,
                "sensors": {
                    "distance_cm": sensors.distance_cm,
                    "proximity": "near" if sensors.distance_cm < NEAR_CM else "far",
                    "obstacle": sensors.distance_cm < OBSTACLE_CM,
                    "connected": sensors.connected,
                },
                "motors": self._hardware.motor_states(),
                "events": self._events.recent(),
            }

    # ---------- comandos ----------
    def execute(self, action: str, *, quiet: bool = False) -> None:
        """Valida (lista permitida, emergência, conexão, obstáculo) e só então aciona o hardware."""
        if action not in ALLOWED_ACTIONS:
            raise RobotError(f"Comando não permitido: {action}")
        with self._state.lock:
            self._expire_gesture()
            s = self._state.state
            sensors = self._hardware.read_sensors()
            if s.emergency_stop:
                raise EmergencyStopActive("O simulador está bloqueado pela parada de emergência.")
            if not sensors.connected and action not in ("stop", "idle"):
                raise RobotError("O robô está desconectado; só é possível parar ou aguardar.")
            if action == "wheels_forward" and sensors.distance_cm < OBSTACLE_CM:
                raise RobotError(
                    f"Obstáculo a {sensors.distance_cm} cm: avanço bloqueado por segurança."
                )
            self._hardware.perform(action)
            if action in EXPRESSIONS:
                s.expression = action
                if not quiet:
                    self._events.record(f"Expressão: {EXPRESSIONS[action].lower()}.")
            else:
                self._set_movement(action)
                if not quiet:
                    self._events.record(f"Simulador: {MOVEMENTS[action].lower()}.")

    def react_to_chat(self, intent: str | None) -> None:
        """Reação do robô à conversa. A IA só informa a intenção; a ação passa por execute()."""
        expression, movement = REACTIONS.get(intent or "", DEFAULT_REACTION)
        try:
            self.execute(expression, quiet=True)
            if movement:
                self.execute(movement, quiet=True)
        except RobotError as error:
            logger.info("Reação à conversa ignorada: %s", error.detail)

    def update_simulated_sensors(self, distance_cm: int | None, connected: bool | None) -> None:
        """Altera valores dos sensores simulados e aplica as regras de segurança resultantes."""
        if not isinstance(self._hardware, SimulatedHardware):
            raise RobotError("Sensores só podem ser editados no simulador.")
        with self._state.lock:
            was_connected = self._hardware.read_sensors().connected
            if distance_cm is not None:
                self._hardware.set_distance(distance_cm)
            if connected is not None:
                self._hardware.set_connected(connected)
            self._apply_sensor_safety(was_connected)

    def set_hardware_mode(self, mode: str) -> None:
        """Alterna entre simulador e hardware físico. Se o físico falhar, o simulador permanece ativo."""
        if mode not in ("simulation", "physical"):
            raise RobotError(f"Modo de hardware inválido: {mode}")
        with self._state.lock:
            if mode == "simulation":
                self.hardware_error = None
                if not isinstance(self._hardware, SimulatedHardware):
                    self._swap_hardware(SimulatedHardware())
                self._events.record("Modo simulado ativado.")
                return
            candidate = PhysicalHardware()
            try:
                candidate.connect()
            except HardwareUnavailable as error:
                self.hardware_error = error.detail
                self._events.record("Hardware físico indisponível: simulador mantido.")
                logger.warning("Hardware físico indisponível: %s", error.detail)
                raise
            self.hardware_error = None
            self._swap_hardware(candidate)
            self._events.record("Modo físico ativado.")

    def start_demo(self) -> None:
        with self._state.lock:
            s = self._state.state
            if s.emergency_stop:
                raise EmergencyStopActive("Libere a parada de emergência antes de iniciar a demonstração.")
            if not s.session_active:
                self.start_session()
            s.demo_active = True
            self._events.record("Demonstração iniciada.")

    def stop_demo(self) -> None:
        with self._state.lock:
            s = self._state.state
            if not s.demo_active:
                return
            s.demo_active = False
            if not s.emergency_stop and self._hardware.read_sensors().connected:
                self._hardware.perform("idle")
                self._hardware.perform("neutral")
                s.expression = "neutral"
                self._set_movement("idle")
            self._events.record("Demonstração encerrada.")

    def start_session(self) -> None:
        with self._state.lock:
            s = self._state.state
            if s.emergency_stop:
                raise EmergencyStopActive("Libere a parada de emergência antes de iniciar uma sessão.")
            s.session_active = True
            if self._hardware.read_sensors().connected:
                self._hardware.perform("idle")
                self._hardware.perform("neutral")
                s.expression = "neutral"
                self._set_movement("idle")
            self._events.record("Sessão iniciada.")

    def stop_session(self) -> None:
        with self._state.lock:
            s = self._state.state
            self._hardware.halt()
            s.session_active = False
            s.demo_active = False
            s.robot_state = "Offline"
            s.simulator_action = "stop"
            s.expression = "neutral" if self._hardware.read_sensors().connected else "disconnected"
            self._events.record("Sessão encerrada.")

    def toggle_emergency(self) -> None:
        with self._state.lock:
            s = self._state.state
            s.emergency_stop = not s.emergency_stop
            if s.emergency_stop:
                self._hardware.halt()
                s.session_active = False
                s.demo_active = False
                s.robot_state = "Erro"
                s.simulator_action = "stop"
                self._events.record("Parada de emergência acionada.")
            else:
                self._hardware.perform("idle")
                self._set_movement("idle")
                self._events.record("Parada de emergência liberada.")

    def assert_not_stopped(self) -> None:
        with self._state.lock:
            if self._state.state.emergency_stop:
                raise EmergencyStopActive("A parada de emergência está acionada.")

    def note_chat_reply(self, source: str) -> None:
        """Registra apenas a origem da resposta, nunca o conteúdo da conversa."""
        with self._state.lock:
            self._events.record(f"Resposta enviada (origem: {source}).")

    # ---------- internos (chamar com o lock) ----------
    def _swap_hardware(self, hardware: RobotHardware) -> None:
        s = self._state.state
        self._hardware.halt()
        self._hardware = hardware
        s.expression = "neutral"
        s.simulator_action = "idle"
        s.robot_state = MOVEMENTS["idle"]
        s.demo_active = False

    def _set_movement(self, movement: str) -> None:
        s = self._state.state
        s.simulator_action = movement
        s.robot_state = MOVEMENTS[movement]
        s.movement_started = self._clock()

    def _expire_gesture(self) -> None:
        s = self._state.state
        if (
            s.simulator_action in MOMENTARY_MOVEMENTS
            and self._clock() - s.movement_started >= GESTURE_SECONDS
        ):
            self._hardware.perform("idle")
            self._set_movement("idle")

    def _apply_sensor_safety(self, was_connected: bool) -> None:
        s = self._state.state
        sensors = self._hardware.read_sensors()
        if was_connected and not sensors.connected:
            self._hardware.halt()
            self._hardware.perform("disconnected")
            s.simulator_action = "stop"
            s.robot_state = MOVEMENTS["stop"]
            s.expression = "disconnected"
            self._events.record("Robô desconectado: movimentos interrompidos.")
        elif not was_connected and sensors.connected:
            self._hardware.perform("neutral")
            s.expression = "neutral"
            self._events.record("Robô reconectado.")
        if (
            sensors.connected
            and sensors.distance_cm < OBSTACLE_CM
            and s.simulator_action == "wheels_forward"
        ):
            self._hardware.halt()
            self._hardware.perform("surprised")
            s.simulator_action = "stop"
            s.robot_state = MOVEMENTS["stop"]
            s.expression = "surprised"
            self._events.record("Obstáculo detectado: rodas paradas.")
