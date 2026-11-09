"""Interface comum de provedor de IA e erros tipados."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal

ErrorKind = Literal[
    "invalid_key",
    "rate_limited",
    "unavailable",
    "model_unavailable",
    "empty_response",
]


class AIError(Exception):
    """Falha ao usar o provedor de IA. Nunca carrega a chave nem o conteúdo da conversa."""

    def __init__(self, kind: ErrorKind, message: str = "") -> None:
        super().__init__(message or kind)
        self.kind: ErrorKind = kind


@dataclass(frozen=True)
class SearchAnswer:
    text: str
    sources: tuple[tuple[str, str], ...] = ()  # (título, endereço) das páginas usadas


@dataclass(frozen=True)
class Turn:
    role: Literal["user", "model"]
    text: str


class AIProvider(ABC):
    name: str

    @abstractmethod
    def is_configured(self) -> bool:
        """Há credenciais para tentar usar o provedor?"""

    @abstractmethod
    def check_availability(self) -> None:
        """Verifica chave, modelo e conectividade. Levanta AIError se indisponível."""

    @abstractmethod
    def generate(
        self, history: list[Turn], message: str, context: str | None = None, corporate: bool = False, event: str | None = None
    ) -> str:
        """Gera uma resposta. `context` = dados oficiais recuperados da base; `event` = contexto do evento ativo (dado,
        não instrução). Levanta AIError em qualquer falha."""

    def search(self, query: str, event: str | None = None) -> "SearchAnswer":
        """Pesquisa externa (camada 3): resposta + fontes públicas encontradas. Levanta AIError se indisponível."""
        raise AIError("unavailable", "pesquisa externa não suportada")
