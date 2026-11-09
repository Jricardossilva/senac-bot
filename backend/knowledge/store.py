"""Carregamento, validação e atualidade da base de conhecimento (arquivos JSON em knowledge/)."""
import json
import logging
import re
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from backend.knowledge.models import (
    CATEGORIES,
    EFFECTIVE,
    FRESHNESS,
    KINDS,
    LEVELS,
    NATURES,
    STATUSES,
    Entry,
    LoadReport,
    Source,
)

logger = logging.getLogger("senac_bot.knowledge")

CATEGORY_FILES = {
    "permanent": "permanent.json",
    "units": "units.json",
    "courses": "courses.json",
    "programs": "programs.json",
    "social": "social.json",
    "empresas": "empresas.json",
    "news_events": "news_events.json",
    "faq": "faq.json",
}
MAX_SPOKEN_WORDS = 90  # as respostas são lidas em voz alta: conteúdo curto por entrada


def _parse_date(value: object, field_name: str, entry_id: str, errors: list[str]) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        errors.append(f"{entry_id}: {field_name} inválido ({value!r}); use AAAA-MM-DD")
        return None


def is_official_url(url: str, allowed_domains: list[str]) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and any(host == d or host.endswith("." + d) for d in allowed_domains)


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def load_sources(directory: Path, report: LoadReport) -> tuple[dict[str, Source], list[str], dict[str, int]]:
    raw = load_json(directory / "sources.json")
    allowed = [d.lower() for d in raw.get("allowed_domains", [])]
    policy = {k: int(v) for k, v in raw.get("freshness_days", {}).items()}
    sources: dict[str, Source] = {}
    for item in raw.get("sources", []):
        try:
            source = Source(
                id=item["id"], name=item["name"], url=item["url"], level=item["level"],
                freshness=item["freshness"], dynamic=bool(item.get("dynamic", False)),
                expect=tuple(item.get("expect", [])), min_length=int(item.get("min_length", 0)),
                noisy=bool(item.get("noisy", False)), category=str(item.get("category", "")), institution=str(item.get("institution", "")),
                kind=str(item.get("kind", "official")),
            )
        except KeyError as error:
            report.errors.append(f"fonte sem campo obrigatório {error}: {item}")
            continue
        if source.id in sources:
            report.errors.append(f"fonte duplicada: {source.id}")
        if not is_official_url(source.url, allowed):
            report.errors.append(f"fonte {source.id}: URL fora dos domínios oficiais ({source.url})")
        if source.freshness not in FRESHNESS:
            report.errors.append(f"fonte {source.id}: freshness inválido")
        sources[source.id] = source
    return sources, allowed, policy


def _words(text: str) -> int:
    return len(re.findall(r"\S+", text))


def build_entry(item: dict, category_file: str, sources: dict[str, Source], allowed: list[str], errors: list[str]) -> Entry | None:
    entry_id = str(item.get("id", "?"))
    required = ("id", "title", "content", "category", "level", "kind", "keywords", "source_ids", "consulted_at", "freshness", "status")
    missing = [key for key in required if key not in item]
    if missing:
        errors.append(f"{entry_id}: campos obrigatórios ausentes: {', '.join(missing)}")
        return None
    problems = len(errors)
    if item["category"] not in CATEGORIES:
        errors.append(f"{entry_id}: categoria inválida ({item['category']})")
    if CATEGORY_FILES.get(item["category"]) != category_file:
        errors.append(f"{entry_id}: categoria {item['category']} está no arquivo errado ({category_file})")
    if item["level"] not in LEVELS:
        errors.append(f"{entry_id}: nível inválido ({item['level']})")
    if item["status"] not in STATUSES:
        errors.append(f"{entry_id}: status inválido ({item['status']})")
    if item["freshness"] not in FRESHNESS:
        errors.append(f"{entry_id}: freshness inválido ({item['freshness']})")
    if item["kind"] not in KINDS:
        errors.append(f"{entry_id}: kind inválido ({item['kind']})")
    if item.get("nature") is not None and item["nature"] not in NATURES:
        errors.append(f"{entry_id}: nature inválido ({item['nature']})")
    if item["category"] in ("social", "news_events") and not item.get("nature"):
        errors.append(f"{entry_id}: ações sociais e eventos precisam de nature (permanente, histórico, vigente ou sem confirmação)")
    if not item["keywords"]:
        errors.append(f"{entry_id}: sem palavras-chave")
    if _words(item["content"]) > MAX_SPOKEN_WORDS:
        errors.append(f"{entry_id}: conteúdo com mais de {MAX_SPOKEN_WORDS} palavras (as respostas são faladas)")
    if item["kind"] in ("institutional", "guidance"):
        if not item["source_ids"]:
            errors.append(f"{entry_id}: informação institucional sem fonte oficial")
        for source_id in item["source_ids"]:
            if source_id not in sources:
                errors.append(f"{entry_id}: fonte inexistente no registro ({source_id})")
    if item.get("url") and not is_official_url(item["url"], allowed):
        errors.append(f"{entry_id}: url fora dos domínios oficiais")
    consulted = _parse_date(item["consulted_at"], "consulted_at", entry_id, errors)
    valid_until = _parse_date(item.get("valid_until"), "valid_until", entry_id, errors)
    if consulted is None or len(errors) > problems:
        return None
    return Entry(
        id=entry_id, title=item["title"], content=item["content"].strip(), category=item["category"],
        level=item["level"], unit=item.get("unit"), kind=item["kind"], keywords=tuple(item["keywords"]),
        questions=tuple(item.get("questions", [])), source_ids=tuple(item["source_ids"]),
        consulted_at=consulted, valid_until=valid_until, freshness=item["freshness"], status=item["status"],
        short=item.get("short"), nature=item.get("nature"), unit_note=item.get("unit_note"), notes=item.get("notes"),
        url=item.get("url"), source_note=item.get("source_note"),
    )


def effective_status(entry: Entry, today: date, policy: dict[str, int], source_state: dict[str, dict]) -> str:
    """pending > stale > review > verified. A fonte alterada sem revisão rebaixa para 'review'."""
    if entry.status == "pending":
        return "pending"
    if entry.valid_until is not None and today > entry.valid_until:
        return "stale"
    max_age = policy.get(entry.freshness)
    if max_age is not None and (today - entry.consulted_at).days > max_age:
        return "stale"
    if entry.status == "review":
        return "review"
    if any(source_state.get(source_id, {}).get("needs_review") for source_id in entry.source_ids):
        return "review"
    return "verified"


def validate_directory(directory: Path) -> LoadReport:
    """Validação completa (usada nos testes e pelo relatório); carrega entradas e acumula todos os problemas."""
    _, report = load_entries(directory)
    return report


def load_entries(directory: Path) -> tuple[dict, LoadReport]:
    report = LoadReport()
    try:
        sources, allowed, policy = load_sources(directory, report)
        aliases = load_json(directory / "aliases.json")
    except (OSError, json.JSONDecodeError) as error:
        report.errors.append(f"não foi possível ler a base: {error}")
        return {"entries": [], "sources": {}, "policy": {}, "aliases": {}, "allowed": []}, report
    entries: list[Entry] = []
    seen: set[str] = set()
    for category, file_name in CATEGORY_FILES.items():
        path = directory / file_name
        try:
            raw = load_json(path)
        except (OSError, json.JSONDecodeError) as error:
            report.errors.append(f"{file_name}: {error}")
            continue
        for item in raw.get("entries", []):
            entry = build_entry(item, file_name, sources, allowed, report.errors)
            if entry is None:
                continue
            if entry.id in seen:
                report.errors.append(f"{entry.id}: id duplicado")
                continue
            if entry.unit is not None and entry.unit not in aliases.get("units", {}):
                report.errors.append(f"{entry.id}: unidade desconhecida ({entry.unit})")
                continue
            seen.add(entry.id)
            entries.append(entry)
    return {"entries": entries, "sources": sources, "policy": policy, "aliases": aliases, "allowed": allowed}, report


def load_source_state(directory: Path) -> dict[str, dict]:
    path = directory / "state.json"
    if not path.exists():
        return {}
    try:
        return load_json(path).get("sources", {})
    except (OSError, json.JSONDecodeError) as error:
        logger.warning("state.json ilegível (%s); ignorando o estado das fontes.", error)
        return {}
