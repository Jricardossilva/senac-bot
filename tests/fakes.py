"""Provedor de IA falso para testes (sem rede, sem chave)."""
from backend.ai.base import AIError, AIProvider, SearchAnswer, Turn


class FakeProvider(AIProvider):
    name = "fake"

    def __init__(
        self,
        configured: bool = True,
        answer: str = "Resposta do Gemini.",
        error: str | None = None,
    ) -> None:
        self.configured = configured
        self.answer = answer
        self.error = error
        self.calls: list[tuple[list[Turn], str]] = []
        self.contexts: list[str | None] = []
        self.corporate_flags: list[bool] = []
        self.events: list[str | None] = []
        self.search_answer: SearchAnswer | None = None  # configurado pelos testes de pesquisa externa
        self.search_error: str | None = None
        self.searches: list[tuple[str, str | None]] = []

    def is_configured(self) -> bool:
        return self.configured

    def check_availability(self) -> None:
        if self.error:
            raise AIError(self.error)  # type: ignore[arg-type]

    def search(self, query: str, event: str | None = None) -> SearchAnswer:
        self.searches.append((query, event))
        if self.search_error:
            raise AIError(self.search_error)  # type: ignore[arg-type]
        if self.search_answer is None:
            raise AIError("unavailable")
        return self.search_answer

    def generate(
        self, history: list[Turn], message: str, context: str | None = None, corporate: bool = False, event: str | None = None
    ) -> str:
        self.events.append(event)
        self.calls.append((list(history), message))
        self.contexts.append(context)
        self.corporate_flags.append(corporate)
        if self.error:
            raise AIError(self.error)  # type: ignore[arg-type]
        return self.answer
