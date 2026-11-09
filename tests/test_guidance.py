"""Orientação para cursos: prioridade CEP-JP > outras unidades do Senac PB > Senac EAD, sem inventar dados."""
import json
import re
import shutil
from datetime import date
from pathlib import Path

import pytest

from backend.guidance import Guidance
from backend.knowledge import KnowledgeBase
from backend.knowledge.offers import EAD_UNIT, Offer
from tests.kb_helpers import KNOWLEDGE_DIR, TEST_TODAY, real_kb

KB = real_kb()


def guidance(kb: KnowledgeBase = KB) -> Guidance:
    return Guidance(kb)


def say(g: Guidance, *messages: str, session: str = "s"):
    return [g.handle(session, m) for m in messages]


def words(text: str) -> int:
    return len(text.split())


def kb_with_offers(tmp_path: Path, extra: list[dict]) -> KnowledgeBase:
    """Cópia da base com ofertas adicionais (para provar a ordem de prioridade com uma oferta do CEP-JP)."""
    target = tmp_path / "knowledge"
    shutil.copytree(KNOWLEDGE_DIR, target, ignore=shutil.ignore_patterns("snapshots"))
    data = json.loads((target / "offers.json").read_text(encoding="utf-8"))
    data["offers"] += extra
    (target / "offers.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return KnowledgeBase.load(target, today=lambda: TEST_TODAY)


def offer(offer_id: str, unit: str | None, keywords: list[str], phrase: str, modality: str = "nao_informada", refine: list[str] | None = None) -> dict:
    return {
        "id": offer_id, "kind": "curso", "unit": unit, "modality": modality, "phrase": phrase, "pitch": "Curso de teste.",
        "keywords": keywords, "refine": refine or [], "source_ids": ["pb-tecnicos"], "evidence": ["Técnico em Informática"],
        "consulted_at": "2026-11-07", "valid_until": "2026-12-07", "freshness": "volatile", "status": "verified",
    }


# ------------------------------------------------------------------------------------------------ catálogo
def test_catalog_loads_without_errors_and_covers_the_three_priorities() -> None:
    assert KB.report.errors == []
    tiers = {o.tier for o in KB.catalog.offers}
    assert tiers == {2, 3}  # nenhuma página oficial confirma ofertas específicas do CEP-JP: nada é inventado
    assert all(o.source_ids and o.evidence for o in KB.catalog.offers)
    assert not any(o.unit == "CEP-JP" for o in KB.catalog.offers)


def test_every_offer_uses_a_real_unit_and_is_not_stale_on_the_reference_date() -> None:
    units = set(KB.aliases["units"]) | {EAD_UNIT, None}
    for o in KB.catalog.offers:
        assert o.unit in units, o.id
        assert KB.effective_offer(o) == "verified", o.id


def test_offers_never_state_prices_hours_dates_or_vacancies() -> None:
    forbidden = re.compile(r"R\$|\d{2,}\s*(horas|h\b)|\bvagas?\b|\d{1,2}/\d{1,2}/\d{2,4}|\bgratuit", re.IGNORECASE)
    for o in KB.catalog.offers:
        assert not forbidden.search(o.phrase + " " + o.pitch), o.id


@pytest.mark.parametrize("change, message", [
    ({"unit": "NAO-EXISTE"}, "unidade inexistente"),
    ({"source_ids": ["fonte-falsa"]}, "fonte inexistente"),
    ({"evidence": []}, "evidence"),
    ({"modality": "ead"}, "EAD"),
    ({"consulted_at": "ontem"}, "data inválida"),
    ({"status": "ok"}, "status inválido"),
    ({"phrase": " ".join(["palavra"] * 40)}, "phrase"),
])
def test_invalid_offers_are_reported_and_ignored(tmp_path: Path, change: dict, message: str) -> None:
    broken = {**offer("off-quebrada", None, ["xyz"], "Frase."), **change}
    kb = kb_with_offers(tmp_path, [broken])
    assert any(message in error for error in kb.report.errors), kb.report.errors
    assert kb.catalog.get("off-quebrada") is None


def test_duplicate_offer_ids_are_rejected(tmp_path: Path) -> None:
    kb = kb_with_offers(tmp_path, [offer("off-tec-informatica", None, ["x"], "Frase.")])
    assert any("duplicado" in e for e in kb.report.errors)


# ------------------------------------------------------------------------------------------------ prioridade
def test_cep_jp_offer_comes_first_when_it_exists(tmp_path: Path) -> None:
    kb = kb_with_offers(tmp_path, [offer("off-cep-jp-robotica", "CEP-JP", ["robotica"], "O CEP João Pessoa tem o curso de Robótica.")])
    ead = offer("off-ead-robotica", EAD_UNIT, ["robotica"], "O Senac EAD tem robótica.", "ead")
    kb2 = kb_with_offers(tmp_path / "b", [ead, offer("off-cep-cg-robotica", "CEP-CG", ["robotica"], "O CEP Campina Grande tem robótica.")])
    reply = guidance(kb).handle("s", "Quero fazer um curso de robótica")
    assert reply is not None and reply.offer_ids == ("off-cep-jp-robotica",)
    assert "Procurei primeiro no CEP" not in reply.text  # a oferta já é do CEP-JP
    other = guidance(kb2).handle("s", "Quero fazer um curso de robótica")
    assert other is not None and other.offer_ids == ("off-cep-cg-robotica",)  # sem CEP-JP: outra unidade, antes da EAD


def test_ead_comes_last_unless_the_visitor_asks_for_it(tmp_path: Path) -> None:
    kb = kb_with_offers(tmp_path, [
        offer("off-ead-robotica", EAD_UNIT, ["robotica"], "O Senac EAD tem robótica.", "ead"),
        offer("off-tec-robotica", None, ["robotica"], "O Senac Paraíba cita robótica."),
    ])
    assert guidance(kb).handle("s", "Quero um curso de robótica").offer_ids == ("off-tec-robotica",)
    assert guidance(kb).handle("s", "Quero um curso de robótica a distância").offer_ids == ("off-ead-robotica",)


def test_unit_known_offers_come_before_unit_unknown_within_the_paraiba_priority() -> None:
    reply = guidance().handle("s", "Quero um curso de beleza")
    assert reply.offer_ids == ("off-cep-cg-beleza",)
    assert "CEP Campina Grande" in reply.text


def test_ead_is_the_last_resort_and_says_so() -> None:
    reply = guidance().handle("s", "Quero fazer um curso de contabilidade")
    assert reply.offer_ids == ("off-ead-contabilidade",)
    assert "Procurei nas unidades da Paraíba, começando pelo CEP João Pessoa" in reply.text


def test_explicit_ead_request_goes_straight_to_ead() -> None:
    reply = guidance().handle("s", "Tem curso EAD?")
    assert reply.offer_ids == ("off-senac-ead",)
    assert "Procurei" not in reply.text
    specific = guidance().handle("s2", "Quero um curso de contabilidade a distância")
    assert specific.offer_ids == ("off-ead-contabilidade",)


def test_first_recommendation_explains_the_cep_jp_search_without_inventing_an_offer() -> None:
    reply = guidance().handle("s", "Tenho interesse em gastronomia")
    assert "Procurei primeiro no CEP João Pessoa, mas não tenho a programação vigente dele confirmada." in reply.text
    assert "Escola Senac de Gastronomia e Hotelaria" in reply.text  # unidade mencionada
    assert reply.offer_ids == ("off-gastro-gastronomia",)
    again = guidance().handle("s-other", "Tenho interesse em gastronomia")
    assert "Procurei primeiro" in again.text  # sessão nova repete o aviso
    follow = say(guidance(), "Tenho interesse em gastronomia", "Quero um curso de turismo")[1]
    assert "Procurei primeiro" not in follow.text  # na mesma sessão o aviso não se repete


# ------------------------------------------------------------------------------------------------ fluxo da conversa
def test_informatica_asks_the_goal_then_recommends() -> None:
    g = guidance()
    first, second = say(g, "Eu gostaria de trabalhar com informática.", "manutenção de computadores")
    assert first.offer_ids == () and first.text.startswith("Que legal!")
    assert "Centro de Educação Profissional de João Pessoa" in first.text
    assert first.text.endswith("Você tem mais interesse em programação, manutenção de computadores ou ferramentas digitais?")
    assert second.offer_ids == ("off-tec-informatica",)
    assert second.text.endswith("Quer conhecer mais detalhes?")


@pytest.mark.parametrize("answer, expected", [
    ("programação", "off-tec-jogos"),
    ("manutenção de computadores", "off-tec-informatica"),
    ("ferramentas digitais", "off-dom-ulrico-informatica"),
])
def test_goal_answer_selects_the_matching_offer(answer: str, expected: str) -> None:
    g = guidance()
    assert say(g, "Quero trabalhar com informática", answer)[1].offer_ids == (expected,)


def test_details_never_invent_data_and_give_official_links() -> None:
    g = guidance()
    _, _, details = say(g, "Eu gostaria de trabalhar com informática.", "manutenção de computadores", "sim")
    assert "Não tenho confirmados preço, carga horária, datas, horários, vagas nem requisitos." in details.text
    assert "filtre pela unidade CEP João Pessoa" in details.text
    assert not re.search(r"R\$|\d", details.text)
    urls = [l.url for l in details.links]
    assert "https://pb.senac.br/matriculas/matricula/cursos-tecnicos/index.php" in urls
    assert all(url.startswith("https://") and ".senac.br" in url for url in urls)


def test_one_recommendation_at_a_time_and_other_option_moves_on() -> None:
    g = guidance()
    messages = say(g, "Quero trabalhar com informática", "programação", "outra opção", "outra opção", "outra opção")
    ids = [m.offer_ids for m in messages[1:]]
    assert ids[0] == ("off-tec-jogos",) and ids[1] != ids[0]
    assert len({i for i in ids if i}) == len([i for i in ids if i])  # nunca repete a mesma oferta
    assert "única opção confirmada" in messages[-1].text or messages[-1].offer_ids


def test_no_means_do_not_insist() -> None:
    g = guidance()
    say(g, "Tenho interesse em gastronomia")
    declined = g.handle("s", "não")
    assert "não vou insistir" in declined.text
    assert g.suggestion("s", "Como a tecnologia muda o mundo?", "Resposta curta.") is None
    # pedido explícito reabre a orientação
    assert g.handle("s", "Quero um curso de turismo").offer_ids


def test_disinterest_statement_is_respected_anywhere() -> None:
    g = guidance()
    assert "não vou insistir" in g.handle("s", "Não tenho interesse em curso").text
    assert g.suggestion("s", "Como a tecnologia ajuda?", "Ajuda muito.") is None


def test_generic_course_request_asks_for_the_area_first() -> None:
    g = guidance()
    first, second = say(g, "Quero fazer um curso", "turismo")
    assert first.text == "Que legal! Em qual área você tem mais interesse: tecnologia, saúde, beleza, gastronomia, turismo ou gestão?"
    assert second.offer_ids and "turismo" in second.text.lower()


def test_unknown_subject_does_not_get_a_made_up_course() -> None:
    reply = guidance().handle("s", "Quero fazer um curso de direito")
    assert reply.offer_ids == ()
    assert "Não encontrei na minha base uma oferta confirmada" in reply.text and reply.links


def test_questions_about_price_hours_or_vacancies_never_get_numbers() -> None:
    for message in ("Quanto custa o curso de informática?", "Tem vagas no curso de enfermagem?", "Qual o horário do curso de estética?", "Quando começa o curso de logística?"):
        reply = guidance().handle("s", message)
        assert reply is not None, message
        assert "Não tenho confirmados preço, carga horária, datas, horários, vagas nem requisitos." in reply.text
        assert not re.search(r"R\$|\d", reply.text)


def test_unit_specific_and_company_questions_are_left_to_the_knowledge_base() -> None:
    assert guidance().handle("s", "O CEP João Pessoa tem curso de informática?") is None
    assert guidance().handle("s", "Onde fica a Escola de Gastronomia e Hotelaria?") is None
    assert guidance().handle("s", "Sou dono de uma empresa e quero capacitar minha equipe") is None
    assert guidance().handle("s", "Sou gerente e quero capacitar meus colaboradores") is None


def test_pure_information_questions_are_not_recommendations() -> None:
    for message in ("Quais cursos técnicos o Senac Paraíba oferece?", "O que é robótica?", "Qual a capital da França?", "Quando o Senac chegou à Paraíba?"):
        assert guidance().handle("s", message) is None, message


# ------------------------------------------------------------------------------------------------ gratuidade
def test_free_courses_point_to_psg_without_promising_free_vacancies() -> None:
    reply = guidance().handle("s", "Tem curso gratuito de enfermagem?")
    assert "nem todos os cursos são gratuitos" in reply.text
    assert "depende da programação, dos critérios e das condições de cada oferta" in reply.text
    assert "dois salários mínimos" in reply.text  # critério vem da base (entrada do PSG), não do modelo
    assert "Não tenho confirmadas as vagas gratuitas atuais." in reply.text
    assert reply.links[0].url == "https://pb.senac.br/programa-senac-de-gratuidade/"
    assert guidance().handle("s", "Tem curso gratuito?").offer_ids == ()


def test_psg_information_questions_go_to_the_knowledge_base() -> None:
    assert guidance().handle("s", "Quem pode fazer curso gratuito?") is None
    assert guidance().handle("s", "Quais os critérios do programa de gratuidade?") is None


# ------------------------------------------------------------------------------------------------ sugestão contextual
def test_suggestion_after_a_related_answer_is_short_and_asks_a_question() -> None:
    g = guidance()
    s = g.suggestion("s", "Como a tecnologia está mudando o trabalho?", "A tecnologia automatiza tarefas repetitivas.")
    assert s is not None and s.text.startswith("Aliás,") and s.text.endswith("Quer saber mais?")
    assert words(s.text) <= 25


def test_suggestion_is_not_repeated_in_every_message() -> None:
    g = guidance()
    assert g.suggestion("s", "Como a tecnologia muda o trabalho?", "Resposta.") is not None
    for _ in range(2):
        g.handle("s", "Ah, entendi")
        assert g.suggestion("s", "E a tecnologia na escola?", "Resposta.") is None  # intervalo mínimo entre sugestões


def test_suggestion_never_repeats_the_same_offer() -> None:
    g = guidance()
    seen = set()
    for i in range(12):
        s = g.suggestion("s", "Fale de tecnologia", "Resposta.")
        g.handle("s", f"conversa {i}")
        if s:
            assert s.offer_ids[0] not in seen
            seen.add(s.offer_ids[0])
            g.handle("s", "ok entendi")  # sai do estágio de detalhes
    assert seen


def test_no_suggestion_without_a_related_subject_or_for_long_answers_or_unit_questions() -> None:
    g = guidance()
    assert g.suggestion("s", "Qual a capital da França?", "Paris.") is None
    assert g.suggestion("s", "Como a tecnologia ajuda?", " ".join(["palavra"] * 60)) is None
    assert g.suggestion("s", "O CEP João Pessoa tem tecnologia?", "Resposta.") is None


def test_state_is_per_session_and_cleared() -> None:
    g = guidance()
    say(g, "Quero trabalhar com informática", session="a")
    assert g.handle("b", "programação") is None  # outra sessão não herda o estágio
    g.clear()
    assert g.handle("a", "programação") is None


# ------------------------------------------------------------------------------------------------ formato
@pytest.mark.parametrize("script", [
    ["Eu gostaria de trabalhar com informática.", "manutenção de computadores", "sim", "sim"],
    ["Tenho interesse em gastronomia", "sim"],
    ["Quero um curso de beleza", "sim"],
    ["Quero um curso de contabilidade", "sim"],
    ["Tem curso EAD?"],
    ["Quero fazer um curso", "saúde", "sim"],
    ["Tem curso gratuito de informática?"],
    ["Quanto custa o curso de logística?"],
    ["Quero fazer um curso de direito"],
])
def test_replies_are_short_spoken_text_with_one_question_and_no_urls(script: list[str]) -> None:
    g = guidance()
    for reply in say(g, *script):
        assert reply is not None
        assert words(reply.text) <= 70, (words(reply.text), reply.text)
        assert "http" not in reply.text and "www." not in reply.text
        assert reply.text.count("?") == 1 and reply.text.rstrip().endswith("?"), reply.text
        assert "**" not in reply.text and "\n" not in reply.text


def test_stale_offers_are_flagged_and_pending_ones_are_not_recommended(tmp_path: Path) -> None:
    late = Guidance(KnowledgeBase.load(KNOWLEDGE_DIR, today=lambda: date(2027, 3, 1)))
    reply = late.handle("s", "Tenho interesse em gastronomia")
    assert "Essa informação pode estar desatualizada." in reply.text
    pending = {**offer("off-pendente", None, ["xadrez"], "O Senac cita xadrez."), "status": "pending"}
    assert guidance(kb_with_offers(tmp_path, [pending])).handle("s", "Quero um curso de xadrez").offer_ids == ()
