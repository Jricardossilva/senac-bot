"""Extração do portal de cursos no MySQL: sobrevive a reinícios (Render), banco fora do ar e semente versionada (sem servidor MySQL)."""
import json

import pytest

from backend.eventkb import EventStore
from backend.knowledge import KnowledgeBase
from backend.knowledge.portal import PORTAL_KEY, PortalExtractor, PortalKnowledge, PortalLookup, PortalStorageError
from tests.kb_helpers import TEST_TODAY
from tests.test_eventkb_mysql import FakeDB, make
from tests.test_portal import Portal, kb_dir  # noqa: F401 - kb_dir é uma fixture

STAMP = "2026-11-07T12:00:00+00:00"


@pytest.fixture
def db():
    return FakeDB()


def extractor(kb_dir, portal, storage):  # noqa: F811
    kb = KnowledgeBase.load(kb_dir, today=lambda: TEST_TODAY)
    return kb, PortalExtractor(kb_dir, kb, portal.fetcher, today=lambda: TEST_TODAY, now=lambda: STAMP, storage=storage)


def test_extraction_goes_to_the_database_and_survives_a_restart(db, kb_dir) -> None:  # noqa: F811
    kb, first = extractor(kb_dir, Portal(), make(db))
    assert first.refresh().outcome == "extracted"
    assert PORTAL_KEY in db.rows and not (kb_dir / "extractions").exists()  # nada foi gravado em disco

    after_restart = Portal()  # novo servidor (Render acordou/redeployou): disco zerado, banco com a extração
    kb2, second = extractor(kb_dir, after_restart, make(db))
    assert second.refresh_if_stale() is None and after_restart.requests == []  # já consultada hoje: não volta ao portal
    assert len(second.store.load()["offerings"]) == 4 and second.store.summary()["storage"] == "mysql"
    found = PortalLookup(second.store, kb2, clock=lambda: TEST_TODAY).find("Quero um curso de Excel")
    assert [o["id"] for o in found] == [1]  # o chat usa a extração que veio do banco


def test_operator_decisions_survive_a_restart(db, kb_dir) -> None:  # noqa: F811
    _, first = extractor(kb_dir, Portal(), make(db))
    first.refresh()
    first.store.decide("unit-CEP-JP", "approve")
    first.store.decide("unit-PATOS", "reject")
    _, second = extractor(kb_dir, Portal(), make(db))
    records = {r["id"]: r for r in second.store.load()["records"]}
    assert records["unit-CEP-JP"]["status"] == "confirmed" and records["unit-CEP-JP"]["approved_by"] == "operator"
    assert records["unit-PATOS"]["status"] == "rejected"


def test_the_versioned_file_is_only_the_seed_while_the_database_is_empty(db, kb_dir) -> None:  # noqa: F811
    seed_path = kb_dir / "extractions" / "pb-programacao-cursos.json"
    seed_path.parent.mkdir(parents=True)
    seed_path.write_text(json.dumps({"consulted_at": "2026-11-06T09:00:00+00:00", "offerings": [{"id": 99}]}), encoding="utf-8")
    store = PortalKnowledge(kb_dir, storage=make(db))
    assert store.load()["offerings"] == [{"id": 99}]  # banco vazio: usa a semente
    store.save({"consulted_at": STAMP, "offerings": [{"id": 1}]})
    assert store.load()["offerings"] == [{"id": 1}]  # depois da primeira gravação, o banco vale mais que o arquivo
    assert json.loads(seed_path.read_text(encoding="utf-8"))["offerings"] == [{"id": 99}]  # o arquivo não é tocado


def test_database_down_on_start_falls_back_to_the_seed_and_the_chat_keeps_answering(db, kb_dir) -> None:  # noqa: F811
    seed_path = kb_dir / "extractions" / "pb-programacao-cursos.json"
    seed_path.parent.mkdir(parents=True)
    seed_path.write_text(json.dumps({"consulted_at": "2026-11-06T09:00:00+00:00", "offerings": [{"id": 99}]}), encoding="utf-8")
    storage = make(db)
    db.down = True
    assert PortalKnowledge(kb_dir, storage=storage).load()["offerings"] == [{"id": 99}]


def test_database_down_on_refresh_keeps_fresh_data_for_this_run_and_warns(db, kb_dir) -> None:  # noqa: F811
    storage = make(db)
    kb, ex = extractor(kb_dir, Portal(), storage)
    db.down = True
    result = ex.refresh()
    assert result.outcome == "extracted" and "Aviso: banco de dados indisponível" in result.detail
    assert len(ex.store.load()["offerings"]) == 4  # o chat já usa a extração nova (arquivo, só nesta execução)
    with pytest.raises(PortalStorageError) as error:
        ex.store.decide("unit-CEP-JP", "approve")  # nunca finge que gravou
    assert "secreto" not in str(error.value) and "abc" not in str(error.value)  # sem credenciais na mensagem


def test_portal_documents_do_not_show_up_as_events(db, kb_dir, tmp_path) -> None:  # noqa: F811
    storage = make(db)
    _, ex = extractor(kb_dir, Portal(), storage)
    ex.refresh()
    assert storage.event_ids() == [] and EventStore(tmp_path / "ev", storage).list_events() == []


def test_loaded_data_is_a_copy_so_callers_never_change_the_cache(db, kb_dir) -> None:  # noqa: F811
    storage = make(db, cache=60)
    _, ex = extractor(kb_dir, Portal(), storage)
    ex.refresh()
    ex.store.load()["offerings"].clear()
    assert len(ex.store.load()["offerings"]) == 4


def test_without_a_database_the_file_is_still_the_only_source(kb_dir) -> None:  # noqa: F811
    _, ex = extractor(kb_dir, Portal(), None)
    assert ex.refresh().outcome == "extracted"
    assert (kb_dir / "extractions" / "pb-programacao-cursos.json").exists() and ex.store.summary()["storage"] == "arquivo"
