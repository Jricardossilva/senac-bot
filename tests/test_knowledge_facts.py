"""Os fatos da base precisam estar escritos nas páginas oficiais consultadas (comparação com os snapshots)."""
import json

import pytest

from backend.knowledge.verify import DEFAULT_DIR, run_checks
from tests.kb_helpers import real_kb

KB = real_kb()
CHECKS = json.loads((DEFAULT_DIR / "fact_checks.json").read_text(encoding="utf-8"))["checks"]


def snapshots_with_text() -> bool:
    paths = list((DEFAULT_DIR / "snapshots").glob("*.json"))
    return bool(paths) and all("text" in json.loads(p.read_text(encoding="utf-8")) for p in paths)


def test_fact_checks_reference_real_entries_and_sources() -> None:
    for check in CHECKS:
        assert KB.get(check["entry"]) is not None, check["entry"]
        assert check["source"] in KB.sources, check
        assert check["source"] in KB.get(check["entry"]).source_ids, f"{check['entry']} não cita a fonte {check['source']}"
        assert check["contains"], check


def test_most_institutional_entries_have_a_fact_check() -> None:
    checked = {c["entry"] for c in CHECKS}
    institutional = [e for e in KB.entries if e.kind != "general" and e.status == "verified"]
    uncovered = [e.id for e in institutional if e.id not in checked]
    assert len(uncovered) / len(institutional) <= 0.25, uncovered


@pytest.mark.skipif(not snapshots_with_text(), reason="rode scripts\\atualizar-conhecimento.ps1 para gerar os snapshots")
def test_every_fact_appears_in_the_official_page() -> None:
    failures = [r for r in run_checks() if not r.ok]
    assert failures == [], "\n".join(f"{r.entry} <- {r.source}: ausente {r.missing}" for r in failures)


@pytest.mark.skipif(not snapshots_with_text(), reason="snapshots ausentes")
def test_snapshots_are_recent_and_hashes_match_state() -> None:
    state = json.loads((DEFAULT_DIR / "state.json").read_text(encoding="utf-8"))["sources"]
    for source_id, info in state.items():
        if KB.sources[source_id].dynamic:
            continue
        assert info["hash"] and info["last_ok"] and info["consecutive_failures"] == 0, source_id
        snapshot = json.loads((DEFAULT_DIR / "snapshots" / f"{source_id}.json").read_text(encoding="utf-8"))
        assert snapshot["sha256"] == info["hash"], source_id
