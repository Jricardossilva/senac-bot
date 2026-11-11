"""Segurança da API: acesso do operador por token e limite de requisições do chat.

- Rotas do operador (tudo em /api/ exceto as públicas abaixo) exigem o cabeçalho X-Operator-Token igual a OPERATOR_TOKEN.
  Sem token configurado: em desenvolvimento ficam abertas (uso local); em produção ficam BLOQUEADAS (nunca abertas por esquecimento).
- O chat tem limite por cliente e global por minuto, em memória (protege a cota do Gemini).
"""
import hmac
import time
from collections import OrderedDict, deque
from threading import Lock

# Rotas /api/ usadas pela tela do visitante (ou somente leitura sem dados sensíveis).
PUBLIC_API_PATHS = frozenset({
    "/api/status",
    "/api/event/active",
    "/api/session/start",
    "/api/session/stop",
    "/api/simulator/action",  # só expressões vindas da conversa; o restante exige operador (ver main.simulator_action)
})
TOKEN_HEADER = "x-operator-token"


def is_operator_path(path: str) -> bool:
    return path.startswith("/api/") and path.rstrip("/") not in PUBLIC_API_PATHS


def operator_access(token: str | None, supplied: str | None, app_env: str) -> tuple[int, str] | None:
    """None = acesso permitido; senão (status HTTP, mensagem)."""
    if not token:
        if app_env == "production":
            return 503, "Acesso do operador desativado: defina OPERATOR_TOKEN no servidor."
        return None
    if not supplied or not hmac.compare_digest(supplied.encode("utf-8"), token.encode("utf-8")):
        return 401, "Acesso restrito ao operador: informe o código de acesso."
    return None


class RateLimiter:
    """Janela deslizante em memória, por chave, com número máximo de chaves (sessões novas em excesso não consomem memória)."""

    def __init__(self, per_key: int, window_seconds: float = 60.0, global_limit: int | None = None, max_keys: int = 500,
                 clock=time.monotonic) -> None:
        self._per_key = per_key
        self._global = global_limit
        self._window = window_seconds
        self._max_keys = max_keys
        self._clock = clock
        self._hits: OrderedDict[str, deque[float]] = OrderedDict()
        self._all: deque[float] = deque()
        self._lock = Lock()

    @property
    def enabled(self) -> bool:
        return self._per_key > 0

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
            self._all.clear()

    def allow(self, key: str) -> bool:
        if not self.enabled:
            return True
        now = self._clock()
        with self._lock:
            while self._all and now - self._all[0] > self._window:
                self._all.popleft()
            hits = self._hits.pop(key, None) or deque()
            while hits and now - hits[0] > self._window:
                hits.popleft()
            self._hits[key] = hits
            while len(self._hits) > self._max_keys:
                self._hits.popitem(last=False)
            if len(hits) >= self._per_key or (self._global is not None and len(self._all) >= self._global):
                return False
            hits.append(now)
            self._all.append(now)
            return True
