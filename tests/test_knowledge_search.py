"""Consulta à base: relevância, unidades, empresas, atualidade e recusa quando não há informação."""
from datetime import date

import pytest

from tests.kb_helpers import real_kb

KB = real_kb()

# pergunta -> ids aceitos na primeira posição
EXPECTED_TOP = [
    ("O que é o Senac?", {"br-senac-o-que-e"}),
    ("Qual a história do Senac Paraíba?", {"pb-historia"}),
    ("Quando o Senac chegou à Paraíba?", {"pb-historia"}),
    ("Qual é a missão do Senac Paraíba?", {"pb-missao-visao-valores"}),
    ("Quais são os valores do Senac?", {"br-missao-visao-valores", "pb-missao-visao-valores"}),
    ("Qual é o modelo pedagógico do Senac?", {"br-modelo-pedagogico", "pb-modelo-pedagogico"}),
    ("O que é o projeto integrador?", {"pb-modelo-pedagogico"}),
    ("Que tipos de cursos o Senac oferece?", {"br-tipos-de-cursos"}),
    ("O Senac tem cursos a distância?", {"br-ead"}),
    ("O que é formação inicial e continuada?", {"br-fic-tecnico-superior"}),
    ("Quais unidades o Senac tem em João Pessoa?", {"units-joao-pessoa-visao-geral"}),
    ("Onde ficam as unidades do Senac?", {"units-paraiba-lista-completa"}),
    ("Quais unidades o Senac possui na Paraíba?", {"units-paraiba-lista-completa"}),
    ("Onde fica o CEP João Pessoa?", {"unit-cep-jp-localizacao"}),
    ("Qual é o telefone do CEP-JP?", {"unit-cep-jp-localizacao"}),
    ("Quando o CEP João Pessoa foi inaugurado?", {"unit-cep-jp-perfil"}),
    ("O que é o CENDEGE?", {"unit-cendege"}),
    ("Onde fica a Escola Senac de Gastronomia e Hotelaria?", {"unit-gastronomia-hotelaria"}),
    ("O que é a Escola Senac Dom Ulrico?", {"unit-dom-ulrico"}),
    ("Onde fica o Senac em Campina Grande?", {"unit-campina-grande"}),
    ("O que são as Unidades Móveis?", {"unit-moveis"}),
    ("Quais cursos técnicos o Senac Paraíba oferece?", {"courses-tecnicos-lista-pb"}),
    ("Quais áreas de formação existem?", {"courses-areas-formacao-pb"}),
    ("Como faço matrícula?", {"courses-matricula"}),
    ("Como me matriculo?", {"courses-matricula"}),
    ("Onde vejo a programação de cursos?", {"courses-como-consultar-programacao"}),
    ("O que é o Programa Senac de Gratuidade?", {"program-psg"}),
    ("Quem pode fazer curso gratuito?", {"program-psg"}),
    ("O que é o Jovem Aprendiz?", {"program-aprendizagem-pb"}),
    ("O Senac ajuda a conseguir emprego?", {"program-banco-oportunidades"}),
    ("O que é o programa 4Rs?", {"social-4rs"}),
    ("O Senac faz campanhas de doação?", {"social-acao-voluntaria"}),
    ("Quais datas ambientais o Senac comemora?", {"social-calendario-socioambiental"}),
    ("O Senac tem programa para pessoas com deficiência?", {"social-acessibilidade"}),
    ("O que é o Senac Empresas?", {"empresas-o-que-e"}),
    ("O Senac atende sindicatos?", {"empresas-sindicatos"}),
    ("Como contrato um treinamento para minha empresa?", {"empresas-atendimento-corporativo-pb", "empresas-como-contratar", "empresas-solucoes"}),
    ("O que é a Semana S?", {"news-2026-04-06-semana-s", "news-2026-05-11-innovation-day"}),
    ("Tem algum evento acontecendo?", {"events-vigentes"}),
    ("Como falo com o Senac Paraíba?", {"faq-canais-oficiais"}),
    ("Quanto custa um curso do Senac?", {"faq-valores-vagas-datas"}),
    ("O que é robótica?", {"faq-robotica"}),
]


@pytest.mark.parametrize("question,expected", EXPECTED_TOP)
def test_questions_find_the_right_entry(question: str, expected: set[str]) -> None:
    result = KB.search(question)
    assert result.confident, question
    assert result.hits[0].entry.id in expected, (question, result.ids)


@pytest.mark.parametrize("question", ["Qual a capital da França?", "Quanto vale o bitcoin hoje?", "Receita de bolo de cenoura", "Quem ganhou a Copa de 2002?"])
def test_unrelated_questions_are_not_answered_from_the_base(question: str) -> None:
    result = KB.search(question)
    assert not result.confident
    assert not result.institutional


@pytest.mark.parametrize("question", [
    "Qual é o salário dos professores do Senac?", "O Senac tem alguma unidade em Recife?", "Qual o CNPJ do Senac Paraíba?",
])
def test_institutional_questions_without_data_are_not_confident(question: str) -> None:
    result = KB.search(question)
    assert result.institutional
    assert not result.confident or result.hits[0].entry.status != "verified" or result.coverage < 0.9


def test_cep_jp_is_distinguished_from_the_other_joao_pessoa_units() -> None:
    cases = {
        "O que o CEP João Pessoa oferece?": "CEP-JP",
        "Onde fica o CENDEGE?": "CENDEGE",
        "Onde fica a Escola de Gastronomia e Hotelaria?": "GASTRO-HOTELARIA",
        "O Centro de Tecnologia José Roberto Tadros tem cursos?": "TADROS",
        "Como chego na Escola Dom Ulrico?": "DOM-ULRICO",
    }
    for question, unit in cases.items():
        result = KB.search(question)
        assert result.unit == unit, question
        for hit in result.hits:
            assert hit.entry.unit in (None, unit), (question, hit.entry.id)


def test_unit_aliases_are_recognized_in_many_forms() -> None:
    for text in ["CEP-JP", "o cep de joao pessoa", "Centro de Educação Profissional de João Pessoa", "cep jp", "Renato Ribeiro Coutinho"]:
        assert KB.search(f"Onde fica {text}?").unit == "CEP-JP", text
    assert KB.search("Onde fica o Senac em João Pessoa?").unit is None  # a cidade sozinha não identifica a unidade


def test_courses_of_other_units_are_never_attributed_to_cep_jp() -> None:
    result = KB.search("Quais cursos o CEP João Pessoa oferece?")
    top = result.hits[0].entry
    assert top.id == "courses-cep-jp-oferta" and KB.effective(top) == "pending"
    answer = KB.answer_for(result)
    assert "Não tenho a lista de cursos" in answer
    for course in ("Enfermagem", "Estética", "Jogos Digitais", "Guia de Turismo"):
        assert course not in answer
    assert "gastronomia" not in " ".join(h.entry.content.lower() for h in result.hits if h.entry.unit)


def test_general_course_list_carries_a_unit_warning_when_a_unit_is_named() -> None:
    result = KB.search("O CEP João Pessoa tem curso técnico de enfermagem?")
    assert result.unit == "CEP-JP"
    answer = KB.answer_for(result)
    assert "enfermagem" not in answer.lower() or "não confirma" in answer or "Não tenho" in answer
    general = next((h.entry for h in result.hits if h.entry.id == "courses-tecnicos-lista-pb"), None)
    if general is not None:
        assert general.unit_note


def test_corporate_questions_surface_senac_empresas() -> None:
    for question in ["Sou empresário e quero capacitar meus colaboradores", "Minha empresa pode contratar o Senac?", "O Senac atende empresas?"]:
        result = KB.search(question)
        assert result.corporate, question
        assert any(h.entry.category == "empresas" for h in result.hits), question


def test_corporate_hint_is_added_to_extractive_answer_outside_empresas() -> None:
    result = KB.search("Sou empresário, qual a história do Senac?")
    assert result.corporate
    answer = KB.answer_for(result)
    assert "Senac Empresas" in answer


def test_empresas_answers_do_not_invent_prices_or_proposals() -> None:
    for entry in (e for e in KB.entries if e.category == "empresas"):
        assert "R$" not in entry.content, entry.id
    answer = KB.answer_for(KB.search("Quanto custa um treinamento para minha empresa?"))
    assert "R$" not in answer
    assert "(83) 3208-3100" in answer or "pb.senac.br" in answer


def test_stale_news_carry_a_validity_warning() -> None:
    answer = KB.answer_for(KB.search("O que é a Semana S?"))
    assert "pode ter mudado" in answer or "Notícia datada" in answer or "datada" in answer
    fresh_kb = real_kb(date(2026, 5, 20))
    result = fresh_kb.search("Tem vagas gratuitas na Semana S?")
    assert fresh_kb.effective(result.hits[0].entry) == "verified"


def test_pending_and_review_entries_point_to_official_channels() -> None:
    for question in ["O Senac atende sindicatos?", "Onde fica a Escola de Gastronomia e Hotelaria?", "Quais cursos o CEP João Pessoa oferece?"]:
        answer = KB.answer_for(KB.search(question))
        assert "(83) 3208-3100" in answer or "confirm" in answer.lower() or "procure" in answer.lower(), question


def test_divergent_address_is_reported_as_divergent_not_picked() -> None:
    entry = KB.get("unit-gastronomia-hotelaria")
    assert "divergem" in entry.content
    assert "Cabo Branco" not in entry.content and "Antônio Lira" not in entry.content  # nenhum dos dois é afirmado como certo
    assert "Cabo Branco" in entry.notes and "Antônio Lira" in entry.notes


def test_search_is_fast_enough_for_conversation() -> None:
    import time

    start = time.perf_counter()
    for _ in range(50):
        KB.search("Quais cursos técnicos o Senac Paraíba oferece em João Pessoa?")
    assert (time.perf_counter() - start) / 50 < 0.05


# ---------------- comparações entre unidades e empresa com intenção clara ----------------

def test_comparing_two_units_keeps_each_one_labeled_and_separate() -> None:
    result = KB.search("Qual a diferença entre o CEP João Pessoa e o CENDEGE?")
    assert result.units == ["CEP-JP", "CENDEGE"] and result.confident
    assert {h.entry.unit for h in result.hits if h.entry.unit} == {"CEP-JP", "CENDEGE"}
    answer = KB.answer_for(result)
    assert "CEP João Pessoa" in answer and "CENDEGE" in answer
    assert "Gastronomia" not in answer and "Dom Ulrico" not in answer


def test_three_unit_aliases_in_one_question_are_all_detected() -> None:
    result = KB.search("Compare o CEP-JP, o CENDEGE e a Escola Dom Ulrico")
    assert result.units == ["CEP-JP", "CENDEGE", "DOM-ULRICO"]
    assert all(h.entry.unit in (None, "CEP-JP", "CENDEGE", "DOM-ULRICO") for h in result.hits)


def test_alias_contained_in_a_longer_one_is_not_a_second_unit() -> None:
    assert KB.search("Onde fica o Centro de Educação Profissional de João Pessoa?").units == ["CEP-JP"]
    assert KB.search("Onde fica a Escola de Gastronomia e Hotelaria?").units == ["GASTRO-HOTELARIA"]


def test_company_owner_is_introduced_to_senac_empresas() -> None:
    result = KB.search("Sou dono de uma empresa e quero treinar minha equipe")
    assert result.corporate and result.confident
    assert result.hits[0].entry.category == "empresas"
    assert "Senac Empresas" in KB.answer_for(result) or "Atendimento Corporativo" in KB.answer_for(result)


def test_the_word_empresa_alone_does_not_force_senac_empresas() -> None:
    result = KB.search("Qual empresa fabrica robôs?")
    assert not result.confident or result.hits[0].entry.category != "empresas"
    assert not result.institutional or result.corporate  # só é tratada como empresa por causa da palavra


def test_no_confirmation_text_is_well_formed() -> None:
    text = KB.no_confirmation()
    assert "pelo o" not in text and text.startswith("Não tenho essa informação confirmada.")
    assert "(83) 3208-3100" in text
