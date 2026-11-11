"""Estado da orientação de cursos por sessão: somente em memória, sem texto da conversa (apagado ao encerrar)."""
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from threading import Lock


@dataclass
class GuidanceState:
    stage: str | None = None  # None | "clarify" (perguntou o objetivo) | "details" (ofereceu detalhes) | "more" (ofereceu outra opção)
    area_id: str | None = None
    topic_text: str = ""  # texto usado para casar ofertas (assunto do visitante, sem dados pessoais)
    last_offer_id: str | None = None
    recommended: list[str] = field(default_factory=list)
    clarified_areas: set[str] = field(default_factory=set)
    declined: bool = False  # visitante demonstrou desinteresse: não insistir
    cep_checked: bool = False  # já avisou que a programação do CEP-JP foi a primeira consultada
    greeted: bool = False
    since_last: int = 99  # mensagens desde a última recomendação (evita repetir em todas as respostas)


class GuidanceSessions:
    def __init__(self, max_sessions: int = 50, ttl_seconds: float = 1800.0) -> None:
        self._max = max_sessions
        self._ttl = ttl_seconds
        self._data: OrderedDict[str, tuple[float, GuidanceState]] = OrderedDict()
        self._lock = Lock()

    def get(self, session_id: str | None) -> GuidanceState:
        """Estado da sessão (criado se não existir). Sem sessão, devolve um estado descartável."""
        if not session_id:
            return GuidanceState()
        now = time.monotonic()
        with self._lock:
            for key in [k for k, (ts, _) in self._data.items() if now - ts > self._ttl]:
                del self._data[key]
            _, state = self._data.pop(session_id, (now, GuidanceState()))
            self._data[session_id] = (now, state)
            while len(self._data) > self._max:
                self._data.popitem(last=False)
            return state

    def discard(self, session_id: str | None) -> None:
        if not session_id:
            return
        with self._lock:
            self._data.pop(session_id, None)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
