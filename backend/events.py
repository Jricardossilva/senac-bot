"""Gerenciador de eventos recentes (somente mensagens operacionais, sem conteúdo de conversas)."""
from collections import deque
from threading import Lock


class EventManager:
    def __init__(self, max_events: int = 8) -> None:
        self._events: deque[str] = deque(maxlen=max_events)
        self._lock = Lock()

    def record(self, message: str) -> None:
        with self._lock:
            self._events.appendleft(message)

    def recent(self) -> list[str]:
        with self._lock:
            return list(self._events)
