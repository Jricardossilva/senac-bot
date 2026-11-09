"""Estrutura, fontes e validação da base de conhecimento real (arquivos knowledge/*.json)."""
import json
import shutil
from datetime import date
from pathlib import Path

import pytest

from backend.knowledge.models import CATEGORIES, LEVELS
from backend.knowledge.store import MAX_SPOKEN_WORDS, effective_status, is_official_url, load_entries, validate_directory
from tests.kb_helpers import KNOWLEDGE_DIR, TEST_TODAY, real_kb


def test_real_knowledge_base_is_valid() -> None:
    report = validate_directory(KNOWLEDGE_DIR)
    assert report.errors == []


def test_all_eight_categories_and_three_levels_are_populated() -> None:
    kb = real_kb()
    assert {e.category for e in kb.entries} == set(CATEGORIES)
    assert {e.level for e in kb.entries} == set(LEVELS)
    assert len(kb.entries) >= 60


def test_cep_jp_has_its_own_entries_in_every_relevant_area() -> None:
    kb = real_kb()
    cep = [e for e in kb.entries if e.unit == "CEP-JP"]
    assert {e.category for e in cep} >= {"units", "courses", "news_events"}
    assert all(e.level == "cep-jp" for e in cep)
    assert len(cep) >= 4


def test_every_institutional_entry_has_an_official_https_source() -> None:
    kb = real_kb()
    for entry in kb.entries:
        if entry.kind == "general":
            continue
        assert entry.source_ids, entry.id
        for source in kb.sources_of(entry):
            assert is_official_url(source.url, ["senac.br"]), (entry.id, source.url)
        assert entry.consulted_at <= date.today(), entry.id


def test_general_entries_are_marked_and_not_presented_as_institutional() -> None:
    kb = real_kb()
    general = [e for e in kb.entries if e.kind == "general"]
    assert general and all(e.source_note for e in general)
    assert not any(e.kind == "general" and e.category != "faq" for e in kb.entries)


def test_sources_registry_is_official_only_and_complete() -> None:
    kb = real_kb()
    assert len(kb.sources) >= 15
    assert all(s.url.startswith("https://") and "senac.br" in s.url for s in kb.sources.values())
    used = {sid for e in kb.entries for sid in e.source_ids}
    assert used <= set(kb.sources)


def test_content_is_short_enough_to_be_spoken() -> None:
    for entry in real_kb().entries:
        assert len(entry.content.split()) <= MAX_SPOKEN_WORDS, entry.id


# Referências legítimas entre unidades, como aparecem na fonte oficial (ex.: o CENDEGE funciona
# provisoriamente no CEP João Pessoa). Não são atribuição de conteúdo de uma unidade à outra.
ALLOWED_MENTIONS = {"unit-cendege": {"CEP-JP"}}


def test_entries_of_one_unit_never_describe_another_unit() -> None:
    kb = real_kb()
    for entry in kb.entries:
        if entry.unit is None:
            continue
        for other, data in kb.aliases["units"].items():
            if other == entry.unit or other in ALLOWED_MENTIONS.get(entry.id, set()):
                continue
            for alias in data["aliases"]:
                if len(alias) >= 8 and alias in entry.content.lower().replace("ã", "a").replace("é", "e").replace("ç", "c"):
                    pytest.fail(f"{entry.id} (unidade {entry.unit}) cita {other}: {alias}")


def test_pending_file_references_registered_sources() -> None:
    kb = real_kb()
    assert len(kb.pending) >= 15
    for item in kb.pending:
        assert item["topic"] and item["reason"] and item["action"]
        assert set(item["source_ids"]) <= set(kb.sources), item["id"]


def test_pending_status_is_never_presented_as_verified() -> None:
    kb = real_kb()
    for entry in kb.entries:
        if entry.status == "pending":
            assert kb.effective(entry) == "pending"


def test_divergent_sources_are_flagged_for_review() -> None:
    kb = real_kb()
    for entry_id in ("unit-gastronomia-hotelaria", "unit-cajazeiras", "unit-cendege", "br-numeros"):
        assert kb.get(entry_id).status == "review", entry_id
        assert kb.effective(kb.get(entry_id)) == "review"


def test_news_are_dated_and_expire() -> None:
    kb = real_kb(TEST_TODAY)
    news = [e for e in kb.entries if e.id.startswith("news-")]
    assert len(news) >= 4
    assert all(e.valid_until is not None for e in news)
    assert all(kb.effective(e) == "stale" for e in news)  # março a maio de 2026: já vencidas em novembro
    before = real_kb(date(2026, 5, 20))
    assert before.effective(before.get("news-2026-05-13-vagas-semana-s")) == "verified"


def test_effective_status_rules() -> None:
    kb = real_kb(TEST_TODAY)
    entry = kb.get("br-senac-o-que-e")
    policy = kb.policy
    assert effective_status(entry, TEST_TODAY, policy, {}) == "verified"
    assert effective_status(entry, date(2028, 1, 1), policy, {}) == "stale"  # permanente: 365 dias
    changed = {"br-sobre": {"needs_review": True}}
    assert effective_status(entry, TEST_TODAY, policy, changed) == "review"


def _copy(tmp_path: Path) -> Path:
    target = tmp_path / "knowledge"
    shutil.copytree(KNOWLEDGE_DIR, target, ignore=shutil.ignore_patterns("snapshots", "state.json"))
    return target


def _mutate(directory: Path, file_name: str, mutator) -> None:
    path = directory / file_name
    data = json.loads(path.read_text(encoding="utf-8"))
    mutator(data)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_validation_rejects_institutional_entry_without_source(tmp_path) -> None:
    directory = _copy(tmp_path)
    _mutate(directory, "units.json", lambda d: d["entries"][0].update(source_ids=[]))
    assert any("sem fonte oficial" in e for e in validate_directory(directory).errors)


def test_validation_rejects_unregistered_source_and_unofficial_domain(tmp_path) -> None:
    directory = _copy(tmp_path)
    _mutate(directory, "units.json", lambda d: d["entries"][0].update(source_ids=["blog-qualquer"]))
    assert any("fonte inexistente" in e for e in validate_directory(directory).errors)
    directory = _copy(tmp_path / "b")
    _mutate(directory, "sources.json", lambda d: d["sources"][0].update(url="https://blog.exemplo.com.br/senac"))
    assert any("fora dos domínios oficiais" in e for e in validate_directory(directory).errors)


def test_validation_rejects_bad_dates_duplicates_unknown_unit_and_long_text(tmp_path) -> None:
    directory = _copy(tmp_path)

    def mutate(d):
        d["entries"][0]["consulted_at"] = "07/11/2026"
        d["entries"][1]["id"] = d["entries"][2]["id"]
        d["entries"][3]["unit"] = "UNIDADE-INEXISTENTE"
        d["entries"][4]["content"] = "palavra " * (MAX_SPOKEN_WORDS + 5)

    _mutate(directory, "units.json", mutate)
    errors = " | ".join(validate_directory(directory).errors)
    assert "consulted_at inválido" in errors
    assert "id duplicado" in errors
    assert "unidade desconhecida" in errors
    assert "mais de" in errors


def test_validation_rejects_wrong_category_file_and_missing_fields(tmp_path) -> None:
    directory = _copy(tmp_path)
    _mutate(directory, "units.json", lambda d: d["entries"][0].update(category="courses"))
    _mutate(directory, "courses.json", lambda d: d["entries"][0].pop("title"))
    errors = " | ".join(validate_directory(directory).errors)
    assert "arquivo errado" in errors
    assert "campos obrigatórios ausentes" in errors


def test_broken_knowledge_directory_never_crashes_the_loader(tmp_path) -> None:
    data, report = load_entries(tmp_path / "nao-existe")
    assert data["entries"] == [] and report.errors
    from backend.knowledge import KnowledgeBase

    kb = KnowledgeBase.load(tmp_path / "nao-existe")
    assert kb.entries == [] and kb.summary()["loaded"] is False
    assert kb.search("o que é o senac").hits == []


def test_social_actions_and_events_are_classified_by_nature() -> None:
    """Ações permanentes, fatos históricos e o que está sem confirmação nunca se misturam com 'vigente'."""
    kb = real_kb()
    target = [e for e in kb.entries if e.category in ("social", "news_events")]
    assert target and all(e.nature for e in target)
    assert not any(e.nature == "open" for e in target)  # nenhuma fonte confirma inscrições abertas
    assert all(e.nature == "historical" for e in target if e.id.startswith("news-"))
    assert kb.get("social-4rs").nature == "permanent"
    assert kb.get("social-acoes-vigentes").nature == "unconfirmed" and kb.get("events-vigentes").nature == "unconfirmed"


def test_context_tells_gemini_the_nature_of_each_item() -> None:
    kb = real_kb()
    context = kb.context_for(kb.search("O que é o programa 4Rs?"))
    assert "AÇÃO/PROGRAMA PERMANENTE" in context
    context = kb.context_for(kb.search("O que é a Semana S?"))
    assert "FATO HISTÓRICO" in context and "POSSIVELMENTE DESATUALIZADA" in context


def test_validation_requires_nature_for_social_and_events(tmp_path) -> None:
    directory = _copy(tmp_path)
    _mutate(directory, "social.json", lambda d: d["entries"][0].pop("nature"))
    assert any("precisam de nature" in e for e in validate_directory(directory).errors)
    directory = _copy(tmp_path / "b")
    _mutate(directory, "social.json", lambda d: d["entries"][0].update(nature="agora"))
    assert any("nature inválido" in e for e in validate_directory(directory).errors)
