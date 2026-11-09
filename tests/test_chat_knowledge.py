"""Integração: o assistente consulta a base antes de responder perguntas institucionais."""
from fastapi.testclient import TestClient

import backend.main as main
from backend.ai.service import ChatService
from backend.knowledge.compose import ungrounded_numbers
from tests.fakes import FakeProvider
from tests.kb_helpers import real_kb

KB = real_kb()


def service(provider: FakeProvider) -> ChatService:
    return ChatService(provider, knowledge=KB)


def test_institutional_question_sends_official_context_to_gemini() -> None:
    provider = FakeProvider(answer="O CEP João Pessoa fica na Avenida Dom Pedro I, 389, no Centro.")
    reply = service(provider).reply("s", "Onde fica o CEP João Pessoa?")
    assert reply.source == "gemini"
    assert reply.knowledge[0] == "unit-cep-jp-localizacao"
    context = provider.contexts[-1]
    assert "[unit-cep-jp-localizacao]" in context
    assert "Avenida Dom Pedro I, 389" in context
    assert "Unidade: CEP João Pessoa" in context
    assert "Fonte: Senac Paraíba - Unidades Operativas" in context


def test_context_never_mixes_units_when_one_is_named() -> None:
    provider = FakeProvider(answer="O CEP João Pessoa oferece formação inicial e continuada.")
    service(provider).reply("s", "O que o CEP João Pessoa oferece?")
    context = provider.contexts[-1]
    for other in ("unit-cendege", "unit-gastronomia-hotelaria", "unit-tadros", "unit-dom-ulrico"):
        assert other not in context


def test_pending_and_general_scope_are_labeled_in_the_context() -> None:
    provider = FakeProvider(answer="Não tenho a lista confirmada.")
    service(provider).reply("s", "Quais cursos o CEP João Pessoa oferece?")
    assert "SEM CONFIRMAÇÃO" in provider.contexts[-1]
    provider = FakeProvider(answer="Há vários cursos técnicos.")
    service(provider).reply("s", "Quais cursos técnicos o Senac Paraíba oferece?")
    assert "informação geral, não específica de unidade" in provider.contexts[-1]
    assert "Atenção: Não atribuir esses cursos a nenhuma unidade" in provider.contexts[-1]


def test_without_gemini_the_base_answers_directly() -> None:
    for provider in (FakeProvider(configured=False), FakeProvider(error="unavailable"), FakeProvider(error="rate_limited")):
        reply = service(provider).reply("s", "Onde fica o CEP João Pessoa?")
        assert reply.source == "knowledge"
        assert "Avenida Dom Pedro I, 389" in reply.text
        assert reply.knowledge[0] == "unit-cep-jp-localizacao"


def test_invalid_key_still_answers_from_the_base() -> None:
    svc = service(FakeProvider(error="invalid_key"))
    first = svc.reply("s", "Qual é a missão do Senac Paraíba?")
    second = svc.reply("s", "Qual é a missão do Senac Paraíba?")
    assert first.source == second.source == "knowledge"
    assert "educar para o trabalho" in second.text.lower()


def test_gemini_answer_with_invented_numbers_is_discarded() -> None:
    provider = FakeProvider(answer="O CEP João Pessoa atende pelo telefone (83) 99999-0000.")
    reply = service(provider).reply("s", "Qual é o telefone do CEP João Pessoa?")
    assert reply.source == "knowledge" and reply.reason == "ungrounded"
    assert "99999" not in reply.text and "3214-2330" in reply.text


def test_gemini_answer_with_numbers_from_the_base_is_kept() -> None:
    provider = FakeProvider(answer="O telefone do CEP João Pessoa é (83) 3214-2330.")
    reply = service(provider).reply("s", "Qual é o telefone do CEP João Pessoa?")
    assert reply.source == "gemini" and "3214-2330" in reply.text


def test_invented_price_is_discarded() -> None:
    provider = FakeProvider(answer="O curso custa R$ 350 por mês.")
    reply = service(provider).reply("s", "Quanto custa um curso do Senac?")
    assert reply.source == "knowledge" and "R$" not in reply.text


def test_ungrounded_numbers_helper() -> None:
    context = "Telefone (83) 3208-3100. Inaugurado em 1974."
    assert ungrounded_numbers("Ligue (83) 3208-3100", context, "") == []
    assert ungrounded_numbers("Desde 1974", context, "") == []
    assert ungrounded_numbers("São 150 vagas", context, "") == ["150"]
    assert ungrounded_numbers("Custa R$ 50", context, "") != []
    assert ungrounded_numbers("São 150 vagas", context, "quero 150 vagas") == []  # número vindo da pergunta


def test_institutional_question_without_data_does_not_call_gemini_and_does_not_invent() -> None:
    provider = FakeProvider()
    reply = service(provider).reply("s", "Qual é a capacidade do auditório do Senac em Sousa?")
    assert provider.calls == []
    assert reply.source == "knowledge" and reply.reason == "no_match"
    assert reply.text.startswith("Não tenho essa informação confirmada")
    assert "(83) 3208-3100" in reply.text


def test_general_question_goes_to_gemini_without_institutional_context() -> None:
    provider = FakeProvider(answer="Buraco negro é uma região do espaço.")
    reply = service(provider).reply("s", "Explique o que são buracos negros")
    assert reply.source == "gemini" and provider.contexts[-1] is None


def test_general_question_without_gemini_uses_generic_fallback() -> None:
    reply = service(FakeProvider(configured=False)).reply("s", "Explique o que são buracos negros")
    assert reply.source == "fallback"


def test_corporate_visitor_gets_senac_empresas_flag_and_context() -> None:
    provider = FakeProvider(answer="O Senac Empresas tem soluções para equipes.")
    reply = service(provider).reply("s", "Sou empresário e quero capacitar meus colaboradores")
    assert provider.corporate_flags[-1] is True
    assert any(i.startswith("empresas-") for i in reply.knowledge)
    assert "empresas-" in provider.contexts[-1]


def test_corporate_answer_without_gemini_presents_senac_empresas() -> None:
    reply = service(FakeProvider(configured=False)).reply("s", "Sou empresário e quero capacitar meus colaboradores")
    assert "Senac Empresas" in reply.text


def test_required_local_answers_still_work_and_use_the_base_text() -> None:
    svc = service(FakeProvider())
    senac = svc.reply("s", "O que é o Senac?")
    assert senac.source == "local" and senac.text == KB.get("br-senac-o-que-e").content
    assert svc.reply("s", "Bom dia").source == "local"
    robotica = svc.reply("s", "O que é robótica?")
    assert robotica.source == "local" and robotica.text.startswith(KB.get("faq-robotica").content)


def test_stale_news_answer_warns_the_information_may_have_changed() -> None:
    reply = service(FakeProvider(configured=False)).reply("s", "Teve dia de serviços gratuitos em Pocinhos?")
    assert "pode ter mudado" in reply.text
    assert "24 de abril" in reply.text


def test_no_current_events_are_claimed_without_a_source() -> None:
    reply = service(FakeProvider(configured=False)).reply("s", "Tem algum evento acontecendo agora?")
    assert "Não tenho confirmação de eventos" in reply.text


# ---------------- endpoints ----------------

def test_chat_endpoint_returns_knowledge_ids(monkeypatch) -> None:
    monkeypatch.setattr(main, "chat_service", service(FakeProvider(configured=False)))
    client = TestClient(main.app)
    body = client.post("/chat", json={"message": "Onde fica o CEP João Pessoa?", "session_id": "t"}).json()
    assert body["source"] == "knowledge" and body["knowledge"][0] == "unit-cep-jp-localizacao"
    assert body["intent"] == "info"


def test_knowledge_status_and_search_endpoints(monkeypatch) -> None:
    monkeypatch.setattr(main, "chat_service", service(FakeProvider()))
    client = TestClient(main.app)
    status = client.get("/api/knowledge/status").json()
    assert status["loaded"] is True and status["entries"] >= 60
    assert status["by_status"]["pending"] >= 5 and len(status["pending_items"]) >= 15
    assert any(s["id"] == "pb-unidades" for s in status["sources"])
    found = client.get("/api/knowledge/search", params={"q": "Onde fica o CEP-JP?"}).json()
    assert found["unit"] == "CEP-JP" and found["hits"][0]["id"] == "unit-cep-jp-localizacao"
    assert client.get("/api/knowledge/search", params={"q": ""}).json()["hits"] == []


def test_status_snapshot_includes_a_knowledge_summary(monkeypatch) -> None:
    monkeypatch.setattr(main, "chat_service", service(FakeProvider()))
    summary = TestClient(main.app).get("/api/status").json()["knowledge"]
    assert summary["loaded"] is True and summary["entries"] >= 60


def test_endpoints_work_when_the_base_is_missing(monkeypatch) -> None:
    monkeypatch.setattr(main, "chat_service", ChatService(FakeProvider(configured=False)))
    client = TestClient(main.app)
    assert client.get("/api/knowledge/status").json()["loaded"] is False
    assert client.post("/chat", json={"message": "Onde fica o CEP João Pessoa?"}).status_code == 200
