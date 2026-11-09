"""Unidade mais próxima no chat: cálculo determinístico (nunca pelo Gemini), com e sem localização."""
from backend.ai.service import ChatService
from tests.fakes import FakeProvider
from tests.kb_helpers import real_kb

KB = real_kb()
# Bem perto do CEP João Pessoa (ver knowledge/geo.json).
NEAR_CEP_JP = (-7.119, -34.874)


def service() -> ChatService:
    return ChatService(FakeProvider(configured=False), knowledge=KB)


def test_nearest_unit_with_coordinates_uses_haversine_never_gemini() -> None:
    provider = FakeProvider()  # configurado, mas não deve ser chamado
    svc = ChatService(provider, knowledge=KB)
    reply = svc.reply("s1", "Qual é a unidade do Senac mais próxima de mim?", lat=NEAR_CEP_JP[0], lon=NEAR_CEP_JP[1])
    assert reply.source == "knowledge"
    assert "CEP João Pessoa" in reply.text
    assert "linha reta" in reply.text
    assert provider.calls == []  # nunca envia coordenadas nem pede ao Gemini para calcular distância


def test_nearest_unit_without_coordinates_asks_for_city() -> None:
    reply = service().reply("s2", "Tem Senac perto de mim?")
    assert reply.source == "knowledge"
    assert reply.reason == "needs_location"
    assert "cidade" in reply.text.lower()


def test_nearest_unit_resolves_by_city_when_no_coordinates_are_sent() -> None:
    reply = service().reply("s3", "Tem Senac perto de mim? Moro em Campina Grande.")
    assert reply.source == "knowledge"
    assert "CEP Campina Grande" in reply.text
    assert "CEP-CG" in reply.knowledge


def test_nearest_unit_city_without_confirmed_geo_does_not_invent_a_unit() -> None:
    reply = service().reply("s4", "Tem Senac perto de mim? Moro em Patos.")
    # Patos não tem endereço/coordenada confirmados (knowledge/geo.json): não inventa distância nem unidade.
    assert "km" not in reply.text
