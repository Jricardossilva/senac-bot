import httpx
import pytest
from google.genai import errors as genai_errors

from backend.ai.base import AIError
from backend.ai.context import SessionContexts
from backend.ai.gemini import GeminiProvider
from backend.ai.local_answers import FALLBACK_GENERIC, contingency_answer, local_answer
from backend.ai.service import ChatService, redact_personal_data
from tests.fakes import FakeProvider

REQUIRED_LOCAL = [
    "Olá", "Bom dia", "Boa tarde", "Boa noite", "Quem é você?", "O que você faz?",
    "O que é o Senac?", "O que é robótica?", "O que é inteligência artificial?",
    "Você é um robô?", "Como você funciona?", "Conte uma piada", "Faça uma pergunta",
    "Quero um desafio", "Obrigado", "Tchau",
]


@pytest.mark.parametrize("message", REQUIRED_LOCAL)
def test_required_local_answers_exist_and_are_short(message: str) -> None:
    answer = local_answer(message)
    assert answer
    assert len(answer.split()) <= 70


def test_time_of_day_greetings_match() -> None:
    assert local_answer("Boa noite!").startswith("Boa noite")
    assert local_answer("bom dia").startswith("Bom dia")


def test_long_or_open_questions_are_not_answered_locally() -> None:
    assert local_answer("Desafio: qual é a diferença entre inteligência artificial e um robô?") is None
    assert local_answer("Olá, como funciona um motor elétrico de carro?") is None


def test_local_answers_do_not_invent_institutional_facts() -> None:
    senac = local_answer("O que é o Senac?")
    assert "Serviço Nacional de Aprendizagem Comercial" in senac
    assert "R$" not in senac


def test_contingency_uses_knowledge_or_generic() -> None:
    from tests.kb_helpers import real_kb

    kb = real_kb()
    assert "sensores" in contingency_answer("como um robô percebe o ambiente?", kb)
    assert contingency_answer("receita de bolo", kb) == FALLBACK_GENERIC
    assert contingency_answer("receita de bolo") == FALLBACK_GENERIC


def test_local_answer_does_not_call_provider() -> None:
    provider = FakeProvider()
    reply = ChatService(provider).reply("s1", "Tchau")
    assert reply.source == "local"
    assert provider.calls == []


def test_not_configured_uses_fallback_without_calling_provider() -> None:
    provider = FakeProvider(configured=False)
    service = ChatService(provider)
    assert service.ai_status == "not_configured"
    reply = service.reply("s1", "Explique buracos negros")
    assert (reply.source, reply.reason) == ("fallback", "not_configured")
    assert provider.calls == []


def test_configured_provider_answers_with_gemini_source() -> None:
    service = ChatService(FakeProvider())
    assert service.ai_status == "configured"
    reply = service.reply("s1", "Explique buracos negros")
    assert (reply.source, reply.text) == ("gemini", "Resposta do Gemini.")
    assert service.ai_status == "available"


@pytest.mark.parametrize(
    "kind,status",
    [
        ("unavailable", "unavailable"),
        ("rate_limited", "rate_limited"),
        ("invalid_key", "invalid_key"),
        ("model_unavailable", "model_unavailable"),
    ],
)
def test_api_failures_fall_back_locally(kind: str, status: str) -> None:
    service = ChatService(FakeProvider(error=kind))
    reply = service.reply("s1", "Explique buracos negros")
    assert (reply.source, reply.reason) == ("fallback", kind)
    assert reply.text
    assert service.ai_status == status


def test_empty_response_falls_back_without_marking_api_down() -> None:
    service = ChatService(FakeProvider(error="empty_response"))
    reply = service.reply("s1", "Explique buracos negros")
    assert reply.source == "fallback"
    assert service.ai_status == "configured"


def test_invalid_key_stops_further_api_calls() -> None:
    provider = FakeProvider(error="invalid_key")
    service = ChatService(provider)
    service.reply("s1", "pergunta um aberta")
    service.reply("s1", "pergunta dois aberta")
    assert len(provider.calls) == 1


def test_check_ai_updates_status() -> None:
    assert ChatService(FakeProvider(configured=False)).check_ai() == "not_configured"
    assert ChatService(FakeProvider()).check_ai() == "available"
    assert ChatService(FakeProvider(error="unavailable")).check_ai() == "unavailable"


def test_context_is_limited_per_session_and_cleared() -> None:
    contexts = SessionContexts(max_exchanges=2)
    provider = FakeProvider()
    service = ChatService(provider, contexts)
    for i in range(4):
        service.reply("s1", f"pergunta aberta numero {i}")
    history, _ = provider.calls[-1]
    assert len(history) == 4
    assert provider.calls[0][0] == []
    service.reply("s2", "outra sessao aberta")
    assert provider.calls[-1][0] == []
    service.clear_contexts()
    service.reply("s1", "depois de limpar")
    assert provider.calls[-1][0] == []


def test_personal_data_is_redacted_before_sending() -> None:
    provider = FakeProvider()
    ChatService(provider).reply("s1", "Meu email é ana@exemplo.com e tel 83 99999-1234, explique robôs")
    sent = provider.calls[0][1]
    assert "ana@exemplo.com" not in sent and "99999" not in sent
    assert redact_personal_data("CPF 123.456.789-09") == "CPF [removido]"


# ---- GeminiProvider com cliente falso (sem rede) ----


class _Models:
    def __init__(self, behaviors):
        self.behaviors = list(behaviors)
        self.calls = 0

    def _next(self):
        self.calls += 1
        item = self.behaviors.pop(0) if len(self.behaviors) > 1 else self.behaviors[0]
        if isinstance(item, Exception):
            raise item
        return item

    def generate_content(self, **kwargs):
        assert kwargs["model"] == "modelo-x"
        assert kwargs["config"].system_instruction
        return self._next()

    def get(self, **kwargs):
        return self._next()


class _Client:
    def __init__(self, *behaviors):
        self.models = _Models(behaviors)


class _Resp:
    def __init__(self, text):
        self.text = text


def _provider(*behaviors, retries=1):
    sleeps: list[float] = []
    client = _Client(*behaviors)
    provider = GeminiProvider(
        "chave-falsa", "modelo-x", max_retries=retries, client=client, sleep=sleeps.append
    )
    return provider, client, sleeps


def _api_error(code, message="x"):
    return genai_errors.APIError(code, {"error": {"message": message, "status": "X"}})


def test_gemini_returns_text() -> None:
    provider, _, _ = _provider(_Resp("  Oi!  "))
    assert provider.generate([], "oi") == "Oi!"


def test_gemini_not_configured_without_key() -> None:
    assert GeminiProvider("  ", "modelo-x").is_configured() is False
    with pytest.raises(AIError):
        GeminiProvider("", "modelo-x").generate([], "oi")


def test_gemini_empty_response_raises() -> None:
    provider, _, _ = _provider(_Resp(None))
    with pytest.raises(AIError) as exc:
        provider.generate([], "oi")
    assert exc.value.kind == "empty_response"


def test_gemini_retries_transient_then_succeeds() -> None:
    provider, client, sleeps = _provider(_api_error(503), _Resp("ok"))
    assert provider.generate([], "oi") == "ok"
    assert client.models.calls == 2
    assert sleeps == [1.0]


def test_gemini_retry_limit_and_timeout() -> None:
    provider, client, _ = _provider(httpx.ReadTimeout("t"), retries=2)
    with pytest.raises(AIError) as exc:
        provider.generate([], "oi")
    assert exc.value.kind == "unavailable"
    assert client.models.calls == 3


def test_gemini_does_not_retry_invalid_key() -> None:
    provider, client, _ = _provider(_api_error(400, "API key not valid"))
    with pytest.raises(AIError) as exc:
        provider.generate([], "oi")
    assert exc.value.kind == "invalid_key"
    assert client.models.calls == 1


def test_gemini_maps_rate_limit_and_missing_model() -> None:
    for code, kind in ((429, "rate_limited"), (404, "model_unavailable")):
        provider, _, _ = _provider(_api_error(code), retries=0)
        with pytest.raises(AIError) as exc:
            provider.generate([], "oi")
        assert exc.value.kind == kind


def test_gemini_network_failure_is_unavailable() -> None:
    provider, _, _ = _provider(httpx.ConnectError("sem internet"), retries=0)
    with pytest.raises(AIError) as exc:
        provider.check_availability()
    assert exc.value.kind == "unavailable"
    ok, _, _ = _provider(object())
    ok.check_availability()
