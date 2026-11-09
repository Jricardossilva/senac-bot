"""Conferência de fatos: cada trecho afirmado pela base precisa aparecer na última versão consultada da página oficial.

    python -m backend.knowledge.verify

Usa os textos guardados em knowledge/snapshots/ (gerados por `python -m backend.knowledge.update`): funciona offline.
"""
import sys
from dataclasses import dataclass
from pathlib import Path

from backend.knowledge.store import load_json
from backend.knowledge.text import normalize

DEFAULT_DIR = Path(__file__).resolve().parent.parent.parent / "knowledge"


@dataclass
class CheckResult:
    entry: str
    source: str
    missing: list[str]
    no_snapshot: bool = False

    @property
    def ok(self) -> bool:
        return not self.missing and not self.no_snapshot


def run_checks(directory: Path = DEFAULT_DIR) -> list[CheckResult]:
    checks = list(load_json(directory / "fact_checks.json")["checks"])
    offers_path = directory / "offers.json"
    if offers_path.exists():  # cada oferta do catálogo traz trechos literais ("evidence") da página oficial que a cita
        checks += [
            {"entry": offer["id"], "source": offer["source_ids"][0], "contains": offer["evidence"]}
            for offer in load_json(offers_path).get("offers", [])
        ]
    results: list[CheckResult] = []
    texts: dict[str, str | None] = {}
    for check in checks:
        source = check["source"]
        if source not in texts:
            path = directory / "snapshots" / f"{source}.json"
            texts[source] = normalize(load_json(path).get("text", "")) if path.exists() else None
        text = texts[source]
        if not text:
            results.append(CheckResult(check["entry"], source, [], no_snapshot=True))
            continue
        missing = [snippet for snippet in check["contains"] if normalize(snippet) not in text]
        results.append(CheckResult(check["entry"], source, missing))
    return results


def main() -> int:
    results = run_checks()
    bad = [r for r in results if not r.ok]
    for result in results:
        mark = "OK   " if result.ok else ("SEM SNAPSHOT" if result.no_snapshot else "FALHA")
        print(f"{mark} {result.entry:40} <- {result.source}" + (f"  ausente: {result.missing}" if result.missing else ""))
    print(f"\n{len(results) - len(bad)}/{len(results)} conferências OK")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
