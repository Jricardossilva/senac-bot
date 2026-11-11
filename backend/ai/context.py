"""Contexto de conversa limitado, somente em memória e por sessão (nada é gravado em disco)."""
import time
from collections import OrderedDict
from threading import Lock

from backend.ai.base import Turn


class SessionContexts:
    def __init__(self, max_exchanges: int = 6, max_sessions: int = 50, ttl_seconds: float = 1800.0) -> None:
        self._max_turns = max_exchanges * 2
        self._max_sessions = max_sessions
        self._ttl = ttl_seconds
        self._data: OrderedDict[str, tuple[float, list[Turn]]] = OrderedDict()
        self._lock = Lock()

    def _purge(self, now: float) -> None:
        for key in [k for k, (ts, _) in self._data.items() if now - ts > self._ttl]:
            del self._data[key]
        while len(self._data) > self._max_sessions:
            self._data.popitem(last=False)

    def get(self, session_id: str | None) -> list[Turn]:
        if not session_id:
            return []
        with self._lock:
            self._purge(time.monotonic())
            entry = self._data.get(session_id)
            return list(entry[1]) if entry else []

    def add_exchange(self, session_id: str | None, user_text: str, model_text: str) -> None:
        if not session_id:
            return
        now = time.monotonic()
        with self._lock:
            _, turns = self._data.pop(session_id, (now, []))
            turns = (turns + [Turn("user", user_text), Turn("model", model_text)])[-self._max_turns:]
            self._data[session_id] = (now, turns)
            self._purge(now)

    def discard(self, session_id: str | None) -> None:
        """Apaga só o contexto de uma sessão (o visitante que encerrou), sem afetar os demais."""
        if not session_id:
            return
        with self._lock:
            self._data.pop(session_id, None)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
