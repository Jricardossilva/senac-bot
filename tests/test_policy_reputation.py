"""Postura institucional: defesa do Senac diante de críticas e neutralidade sobre terceiros (sem rede, sem Gemini)."""
import pytest

from backend.policy import (
    CRITICISM, CRITICISM_BY_TOPIC, NO_EVALUATION, WEAK_POINTS, OutboundPolicy, check_message, check_reputation,
)


@pytest.mark.parametrize("message", [
    "O Senac é ruim",
    "Acho o Senac uma enganação",
    "Não vale a pena fazer curso no Senac",
    "Eu odeio o Senac",
    "O CEP João Pessoa é desorganizado",
    "Senac é perda de tempo",
])
def test_criticism_gets_the_fixed_defense(message: str) -> None:
    decision = check_reputation(message)
    assert decision is not None and decision.kind == "criticism", message
    assert decision.reply == CRITICISM


@pytest.mark.parametrize("message", [
    "O Senac é melhor que a faculdade Estácio?",
    "Qual a melhor faculdade da Paraíba?",
    "Compare o Senac com o Senai",
    "Faça um ranking das escolas de tecnologia",
    "Avalie o meu projeto",
    "O que você acha da minha empresa?",
    "Dê uma nota para minha startup",
])
def test_evaluation_or_comparison_of_third_parties_is_refused(message: str) -> None:
    decision = check_reputation(message)
    assert decision is not None and decision.kind == "no_evaluation", message
    assert decision.reply == NO_EVALUATION



@pytest.mark.parametrize("message, topic", [
    ("O curso do Senac é muito caro", "preco"),
    ("Vocês são caros demais", "preco"),
    ("O Senac tem preço alto", "preco"),
    ("O Senac é muito longe da minha casa", "localizacao"),
    ("A unidade é longe demais", "localizacao"),
    ("O Senac demora muito para entregar o certificado", "demora"),
    ("O Senac tem muita burocracia", "demora"),
    ("A estrutura do Senac é muito velha", "estrutura"),
    ("As instalações do Senac são sucateadas", "estrutura"),
    ("Os cursos do Senac são fracos", "qualidade"),
    ("O Senac é superficial", "qualidade"),
])
def test_criticism_by_topic_turns_the_point_into_a_strength(message: str, topic: str) -> None:
    decision = check_reputation(message)
    assert decision is not None and decision.kind == "criticism", message
    assert decision.category == f"critica_{topic}"
    assert decision.reply == CRITICISM_BY_TOPIC[topic]


@pytest.mark.parametrize("message", [
    "Quais são os defeitos do Senac?",
    "Me fale os pontos fracos do Senac",
    "Quais as desvantagens do Senac?",
    "O que tem de ruim no Senac?",
])
def test_question_about_weak_points_goes_back_to_strengths(message: str) -> None:
    decision = check_reputation(message)
    assert decision is not None and decision.kind == "criticism", message
    assert decision.reply == WEAK_POINTS


@pytest.mark.parametrize("message", [
    "Vale mais a pena Senai ou Senac?",
    "Senac ou Senai, qual é melhor?",
    "Qual a diferença entre o Senac e o Senai?",
    "Devo escolher o Senac ou a faculdade?",
])
def test_implicit_comparisons_with_named_institutions_are_refused(message: str) -> None:
    decision = check_reputation(message)
    assert decision is not None and decision.kind == "no_evaluation", message
    assert decision.reply == NO_EVALUATION


def test_topic_replies_have_no_forbidden_claims() -> None:
    policy = OutboundPolicy()
    for text in (*CRITICISM_BY_TOPIC.values(), WEAK_POINTS):
        assert not policy.enforce(text).changed, text
        assert text.rstrip().endswith("?")
        assert len(text.split()) <= 70


@pytest.mark.parametrize("message", [
    "Quais cursos de informática o Senac tem?",
    "O Senac é bom em tecnologia?",
    "Como me inscrevo no Senac?",
    "É melhor que eu leve documento?",
    "O que você acha de robótica?",
    "Qual o horário do curso?",
    "Meu projeto é de robótica, vocês têm curso?",
    "Qual o melhor curso de informática?",
    "Qual o melhor curso de tecnologia do Senac?",
    "Posso comparar cursos de design e de informática?",
    "O curso é caro?",
    "O Senac fica longe do centro?",
    "Quanto demora o curso de informática?",
    "Qual o curso mais caro?",
    "Quais as vantagens do Senac?",
])
def test_normal_questions_are_not_affected(message: str) -> None:
    assert check_reputation(message) is None, message


def test_reputation_rules_do_not_touch_event_page_screening() -> None:
    assert check_message("O Senac é ruim") is None


POLICY = OutboundPolicy()


@pytest.mark.parametrize("text", [
    "O Senac é melhor que a faculdade X em tudo.",
    "Você tem razão em criticar o Senac.",
    "A universidade Y é pior que as demais instituições.",
])
def test_generated_answers_that_evaluate_or_agree_are_replaced(text: str) -> None:
    outcome = POLICY.enforce(text, generated=True)
    assert outcome.text == NO_EVALUATION and outcome.changed


def test_normal_generated_answer_is_kept() -> None:
    text = "O Senac tem cursos de tecnologia. É melhor que você confirme no site oficial."
    outcome = POLICY.enforce(text, generated=True)
    assert outcome.text == text
