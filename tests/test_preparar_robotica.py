"""Dados do evento Robótica 2026 aplicados pelo script de preparação (sem rede, sem Gemini)."""
import importlib.util
from pathlib import Path

from backend.eventkb.models import CATEGORIES, MAX_ITEM_WORDS
from backend.policy import check_message
from tests.eventkb_helpers import FakeWeb, make_manager

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "preparar_robotica_2026.py"


def load_script():
    spec = importlib.util.spec_from_file_location("preparar_robotica_2026", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_items_are_speakable_valid_and_not_flagged_by_the_policy() -> None:
    script = load_script()
    titles = set()
    for category, title, content, keywords in script.ITEMS:
        assert category in CATEGORIES, title
        assert 0 < len(keywords) <= 30, title
        assert 0 < len(content.split()) <= MAX_ITEM_WORDS, title
        assert check_message(content) is None, title
        assert (category, title) not in titles
        titles.add((category, title))


def test_event_fields_and_items_apply_through_the_manager(tmp_path) -> None:
    script = load_script()
    manager = make_manager(tmp_path, FakeWeb())
    event = manager.create(dict(
        name="Robótica 2026", area="Tecnologia e robótica", description="Cadastro inicial.",
        start_date="2026-11-23", end_date="2026-11-29", organization="Senac Paraíba", city="João Pessoa", uf="PB",
    ))
    event_id = event["id"]
    manager.update(event_id, script.EVENT_FIELDS)
    for category, title, content, keywords in script.ITEMS:
        manager.add_item(event_id, category, title, content, keywords)
    manager.activate(event_id)

    info = manager.public_info()
    assert info["active"] and info["welcome"] == script.EVENT_FIELDS["welcome"]
    assert info["suggested_questions"] == script.EVENT_FIELDS["suggested_questions"][:6]
    assert len(script.EVENT_FIELDS["suggested_questions"]) <= 6  # a tela só mostra as 6 primeiras

    detail = manager.detail(event_id)
    confirmed = [i for c in detail["categories"] for i in c["items"] if i["status"] == "confirmed"]
    assert len(confirmed) == len(script.ITEMS)


def test_script_states_the_confirmed_visiting_hours_and_does_not_claim_senac_organizes() -> None:
    script = load_script()
    text = " ".join(item[2] for item in script.ITEMS)
    assert "25 a 29 de novembro" in text and "9h às 21h" in text and "23 e 24" in text
    assert "organização responsável pelo evento é Senac" not in text
    assert "estande" in text


def test_visitor_questions_reach_the_right_event_item(tmp_path) -> None:
    script = load_script()
    manager = make_manager(tmp_path, FakeWeb())
    event_id = manager.create(dict(
        name="Robótica 2026", area="Tecnologia e robótica", description="Cadastro inicial.",
        start_date="2026-11-23", end_date="2026-11-29", organization="Senac Paraíba", city="João Pessoa", uf="PB",
    ))["id"]
    manager.update(event_id, script.EVENT_FIELDS)
    for category, title, content, keywords in script.ITEMS:
        manager.add_item(event_id, category, title, content, keywords)
    manager.activate(event_id)
    knowledge = manager.active()
    expected = {
        "Quem organiza o evento?": "Organização",
        "Quando posso visitar o evento?": "Entrada e visitação",
        "Preciso pagar para entrar?": "Entrada e visitação",
        "Tem competição?": "Competições",
        "O que é a OBR?": "Siglas do evento",
        "O que o Senac faz na Robótica 2026?": "Participação do Senac Paraíba",
        "Qual a programação de hoje?": "Programação",
        "Vai ter palestra?": "Programação",
    }
    for question, title in expected.items():
        result = knowledge.search(question)
        assert result.confident and result.hits[0].entry.title == title, (question, [h.entry.title for h in result.hits[:3]])


def test_item_keywords_are_cleaned_and_limited(tmp_path) -> None:
    manager = make_manager(tmp_path, FakeWeb())
    event_id = manager.create(dict(
        name="Robótica 2026", area="Tecnologia e robótica", description="Cadastro inicial.",
        start_date="2026-11-23", end_date="2026-11-29",
    ))["id"]
    item = manager.add_item(event_id, "faq", "Teste", "Texto curto de teste.", ["  Palavra  ", "palavra", "x" * 80] + [f"k{i}" for i in range(50)])
    assert item["keywords"][0] == "Palavra" and len(item["keywords"]) == 30 and len(item["keywords"][1]) == 40
    edited = manager.edit_item(event_id, item["id"], keywords=["novo"])
    assert edited["keywords"] == ["novo"]
