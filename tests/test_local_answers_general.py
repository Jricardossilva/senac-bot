"""Perguntas gerais do estande respondidas sem internet e sem Gemini (base de conhecimento do projeto)."""
import pytest

from backend.ai.local_answers import local_match
from tests.kb_helpers import real_kb


@pytest.mark.parametrize("question, expected", [
    ("Você consegue pensar?", "não penso como uma pessoa"),
    ("Você tem consciência?", "não penso como uma pessoa"),
    ("Como funciona a inteligência artificial?", "aprende com muitos exemplos"),
    ("Quais profissões utilizam inteligência artificial?", "Muitas profissões"),
    ("Como posso começar a estudar programação?", "lógica de programação"),
    ("Como posso aprender robótica?", "lógica de programação"),
    ("Quem criou você?", "criado para o evento"),
])
def test_general_questions_have_local_answers(question: str, expected: str) -> None:
    match = local_match(question, real_kb())
    assert match is not None and expected in match.text, question


def test_bot_description_makes_no_promise_of_a_physical_body() -> None:
    kb = real_kb()
    assert "LEGO" not in kb.get("faq-senac-bot").content
    assert "corpo com peças" not in local_match("Você é um robô de verdade?", kb).text
