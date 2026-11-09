"""Provedor Gemini usando o SDK oficial google-genai (somente no backend)."""
import logging
import time
from collections.abc import Callable
from typing import Any

import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from backend.ai.base import AIError, AIProvider, SearchAnswer, Turn
from backend.ai.persona import SEARCH_RULES, build_system_instruction

logger = logging.getLogger("senac_bot.gemini")

MAX_OUTPUT_TOKENS = 1024  # folga para modelos com raciocínio interno; brevidade vem do prompt
TEMPERATURE = 0.7
GROUNDED_TEMPERATURE = 0.2  # com dados oficiais: menos criatividade, mais fidelidade


def _classify(exc: Exception) -> AIError:
    """Traduz exceções do SDK/rede em AIError, sem expor chave nem texto bruto."""
    if isinstance(exc, AIError):
        return exc
    if isinstance(exc, genai_errors.APIError):
        code = getattr(exc, "code", None)
        text = str(exc).lower()
        if code in (401, 403) or "api key" in text or "api_key_invalid" in text:
            return AIError("invalid_key", f"HTTP {code}")
        if code == 429:
            return AIError("rate_limited", "HTTP 429")
        if code == 404:
            return AIError("model_unavailable", "HTTP 404")
        return AIError("unavailable", f"HTTP {code}")
    if isinstance(exc, (httpx.TimeoutException, TimeoutError)):
        return AIError("unavailable", "timeout")
    if isinstance(exc, (httpx.TransportError, OSError)):
        return AIError("unavailable", "falha de rede")
    return AIError("unavailable", type(exc).__name__)


class GeminiProvider(AIProvider):
    name = "gemini"

    def __init__(
        self,
        api_key: str,
        model: str,
        timeout_seconds: float = 10.0,
        max_retries: int = 1,
        client: Any = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._api_key = api_key.strip()
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._max_retries = max(0, max_retries)
        self._client = client
        self._sleep = sleep

    def is_configured(self) -> bool:
        return bool(self._api_key) and bool(self._model)

    def _get_client(self) -> Any:
        if self._client is None:
            self._client = genai.Client(
                api_key=self._api_key,
                http_options=types.HttpOptions(timeout=int(self._timeout_seconds * 1000)),
            )
        return self._client

    def check_availability(self) -> None:
        if not self.is_configured():
            raise AIError("invalid_key", "chave ou modelo ausente")
        try:
            self._get_client().models.get(model=self._model)
        except Exception as exc:  # noqa: BLE001 - tudo vira AIError tipado
            error = _classify(exc)
            logger.warning("Verificação do Gemini falhou: %s", error.kind)
            raise error from None

    def search(self, query: str, event: str | None = None) -> SearchAnswer:
        """Camada 3: Gemini com a busca do Google. Devolve texto e as páginas usadas (o texto é dado não confiável)."""
        if not self.is_configured():
            raise AIError("invalid_key", "chave ou modelo ausente")
        config = types.GenerateContentConfig(
            system_instruction=build_system_instruction(None, False, event) + SEARCH_RULES,
            tools=[types.Tool(google_search=types.GoogleSearch())],
            max_output_tokens=MAX_OUTPUT_TOKENS, temperature=GROUNDED_TEMPERATURE,
        )
        try:
            response = self._get_client().models.generate_content(model=self._model, contents=query, config=config)
        except Exception as exc:  # noqa: BLE001
            raise _classify(exc) from None
        text = (getattr(response, "text", None) or "").strip()
        sources: list[tuple[str, str]] = []
        try:
            for chunk in response.candidates[0].grounding_metadata.grounding_chunks or []:
                web = getattr(chunk, "web", None)
                if web is not None and getattr(web, "uri", None):
                    sources.append((str(getattr(web, "title", "") or ""), str(web.uri)))
        except (AttributeError, IndexError, TypeError):
            pass
        if not text:
            raise AIError("empty_response", "pesquisa sem resposta")
        return SearchAnswer(text, tuple(sources))

    def generate(
        self, history: list[Turn], message: str, context: str | None = None, corporate: bool = False, event: str | None = None
    ) -> str:
        if not self.is_configured():
            raise AIError("invalid_key", "chave ou modelo ausente")
        contents = [
            types.Content(role=turn.role, parts=[types.Part(text=turn.text)])
            for turn in history
        ]
        contents.append(types.Content(role="user", parts=[types.Part(text=message)]))
        config = types.GenerateContentConfig(
            system_instruction=build_system_instruction(context, corporate, event),
            max_output_tokens=MAX_OUTPUT_TOKENS,
            temperature=GROUNDED_TEMPERATURE if context else TEMPERATURE,
        )
        last_error = AIError("unavailable")
        for attempt in range(self._max_retries + 1):
            try:
                response = self._get_client().models.generate_content(
                    model=self._model, contents=contents, config=config
                )
                text = (getattr(response, "text", None) or "").strip()
                if not text:
                    raise AIError("empty_response", "resposta vazia ou bloqueada")
                return text
            except Exception as exc:  # noqa: BLE001
                last_error = _classify(exc)
                logger.warning(
                    "Gemini falhou (tentativa %d/%d): %s",
                    attempt + 1,
                    self._max_retries + 1,
                    last_error.kind,
                )
                retryable = last_error.kind in ("unavailable", "rate_limited")
                if not retryable or attempt >= self._max_retries:
                    break
                self._sleep(1.0 * (attempt + 1))
        raise last_error
