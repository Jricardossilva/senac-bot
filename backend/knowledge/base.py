"""Base de conhecimento institucional: carrega os arquivos, valida e responde consultas."""
import logging
from collections import Counter
from collections.abc import Callable
from datetime import date
from pathlib import Path

from backend.knowledge.compose import (
    comparison_answer,
    extractive_answer,
    format_context,
    no_confirmation_text,
    first_sentence,
)
import re

from backend.knowledge.geo import GeoUnit, load_geo, nearest
from backend.knowledge.models import Entry, LoadReport, Source
from backend.knowledge.offers import Offer, OfferCatalog, load_offers
from backend.knowledge.search import Searcher, SearchResult
from backend.knowledge.store import effective_status, load_entries, load_json, load_source_state

logger = logging.getLogger("senac_bot.knowledge")
DEFAULT_CHANNELS = "os canais oficiais do Senac Paraíba"
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# telefones com ou sem DDD/DDI, "3208-3100", CEP "58013-020": tudo o que parece número de contato
PHONE_RE = re.compile(r"(?:\+?55[\s-]?)?(?:\(?\d{2}\)?[\s-]?)?9?\d{4}[\s-]?\d{4}|\b\d{5}-\d{3}\b")


def digits_of(text: str) -> str:
    return re.sub(r"\D", "", text)


class KnowledgeBase:
    def __init__(
        self,
        entries: list[Entry],
        sources: dict[str, Source],
        aliases: dict,
        policy: dict[str, int],
        source_state: dict[str, dict] | None = None,
        report: LoadReport | None = None,
        pending: list[dict] | None = None,
        today: Callable[[], date] = date.today,
        catalog: OfferCatalog | None = None,
        geo_units: list[GeoUnit] | None = None,
    ) -> None:
        self.catalog = catalog or OfferCatalog()
        self.geo_units = geo_units or []
        self.entries = entries
        self.sources = sources
        self.aliases = aliases
        self.policy = policy
        self.source_state = source_state or {}
        self.report = report or LoadReport()
        self.pending = pending or []
        self._today = today
        self._by_id = {entry.id: entry for entry in entries}
        self._searcher = Searcher(entries, aliases)
        self._unit_names = {key: data["name"] for key, data in aliases.get("units", {}).items()}
        self._contacts: tuple[frozenset[str], frozenset[str]] | None = None

    @classmethod
    def load(cls, directory: Path, today: Callable[[], date] = date.today) -> "KnowledgeBase":
        data, report = load_entries(directory)
        pending: list[dict] = []
        try:
            pending = load_json(directory / "pending.json").get("items", [])
        except (OSError, ValueError) as error:
            report.warnings.append(f"pending.json não lido: {error}")
        aliases = data["aliases"] or {"units": {}, "stopwords": []}
        catalog = load_offers(directory, data["sources"], set(aliases.get("units", {})), load_json)
        report.errors.extend(catalog.errors)
        for problem in report.errors:
            logger.error("Base de conhecimento: %s", problem)
        geo_units = load_geo(directory, load_json)
        kb = cls(
            data["entries"], data["sources"], aliases, data["policy"],
            load_source_state(directory), report, pending, today, catalog, geo_units,
        )
        logger.info("Base de conhecimento carregada: %d entradas, %d fontes.", len(kb.entries), len(kb.sources))
        return kb

    # ---------- consulta ----------
    def get(self, entry_id: str) -> Entry | None:
        return self._by_id.get(entry_id)

    def effective(self, entry: Entry) -> str:
        return effective_status(entry, self._today(), self.policy, self.source_state)

    def sources_of(self, entry: Entry) -> list[Source]:
        return [self.sources[s] for s in entry.source_ids if s in self.sources]

    def search(self, query: str, limit: int = 3) -> SearchResult:
        return self._searcher.search(query, limit)

    def detect_units(self, query: str) -> list[str]:
        """Unidades citadas na mensagem (chaves de aliases.json)."""
        return self._searcher.detect_units(query)

    def effective_offer(self, offer: Offer) -> str:
        """Situação efetiva de uma oferta (mesmas regras de validade das entradas)."""
        return effective_status(offer, self._today(), self.policy, self.source_state)  # type: ignore[arg-type]

    def public_contact_data(self) -> tuple[frozenset[str], frozenset[str]]:
        """E-mails e números de contato que a base publica (a saída do robô só pode conter estes)."""
        if self._contacts is None:
            text = " ".join(e.content for e in self.entries) + " " + " ".join(e.short or "" for e in self.entries)
            emails = frozenset(m.lower() for m in EMAIL_RE.findall(text))
            numbers = frozenset(digits_of(m) for m in PHONE_RE.findall(text))
            self._contacts = (emails, numbers)
        return self._contacts

    def channels(self) -> str:
        entry = self.get("faq-canais-oficiais")
        return entry.short if entry and entry.short else DEFAULT_CHANNELS

    def context_for(self, result: SearchResult) -> str:
        return format_context(result, self.effective, self._unit_names, self.sources_of)

    def answer_for(self, result: SearchResult) -> str:
        if len(result.units) >= 2:
            return comparison_answer(result, self._unit_names)
        intro = self.get("empresas-o-que-e")
        return extractive_answer(result, self.effective, self.channels(), first_sentence(intro.content) if intro else None)

    def no_confirmation(self) -> str:
        return no_confirmation_text(self.channels())

    def unit_name(self, key: str | None) -> str | None:
        return self._unit_names.get(key) if key else None

    def nearest_units(self, lat: float, lon: float, limit: int = 3) -> list[tuple[GeoUnit, float]]:
        return nearest(self.geo_units, lat, lon, limit)

    def geo_unit_for_municipio(self, municipio: str) -> GeoUnit | None:
        norm = municipio.strip().casefold()
        return next((g for g in self.geo_units if g.municipio.casefold() == norm), None)

    # ---------- estado ----------
    def summary(self) -> dict[str, object]:
        """Resumo curto (vai em /api/status): contagens por situação efetiva das entradas institucionais."""
        institutional = [e for e in self.entries if e.kind != "general"]
        counts = Counter(self.effective(e) for e in institutional)
        return {
            # Itens que exigem atenção do operador: informação central vencida e fontes alteradas sem revisão.
            # (Notícias vencidas e lacunas conhecidas são esperadas e não geram aviso.)
            "stale_core": sum(1 for e in institutional if self.effective(e) == "stale" and e.category != "news_events"),
            "sources_review": sum(1 for s in self.source_state.values() if s.get("needs_review")),
            "sources_failing": sum(1 for s in self.source_state.values() if s.get("consecutive_failures", 0) >= 3),
            "loaded": bool(self.entries) and not self.report.errors,
            "entries": len(self.entries),
            "verified": counts.get("verified", 0),
            "review": counts.get("review", 0),
            "stale": counts.get("stale", 0),
            "pending": counts.get("pending", 0),
            "errors": len(self.report.errors),
        }

    def status(self) -> dict[str, object]:
        today = self._today()
        effective = Counter(self.effective(e) for e in self.entries if e.kind != "general")
        sources = []
        for source in self.sources.values():
            state = self.source_state.get(source.id, {})
            sources.append({
                "id": source.id, "name": source.name, "url": source.url, "dynamic": source.dynamic,
                "category": source.category, "institution": source.institution, "kind": source.kind,
                "last_checked": state.get("last_checked"), "last_ok": state.get("last_ok"),
                "needs_review": bool(state.get("needs_review")), "error": state.get("error"),
                "failures": state.get("consecutive_failures", 0),
            })
        institutional = [e for e in self.entries if e.kind != "general"]
        return {
            "loaded": bool(self.entries) and not self.report.errors,
            "entries": len(self.entries),
            "by_category": dict(Counter(e.category for e in self.entries)),
            "by_level": dict(Counter(e.level for e in self.entries)),
            "by_status": {k: effective.get(k, 0) for k in ("verified", "review", "stale", "pending")},
            "last_consulted": max((e.consulted_at for e in institutional), default=None).isoformat() if institutional else None,
            "today": today.isoformat(),
            "stale": [{"id": e.id, "title": e.title, "valid_until": e.valid_until.isoformat() if e.valid_until else None}
                      for e in institutional if self.effective(e) == "stale"],
            "pending_items": [
                {"id": p.get("id"), "topic": p.get("topic"), "type": p.get("type", "unconfirmed"), "reason": p.get("reason", ""),
                 "action": p.get("action", ""), "source_ids": p.get("source_ids", [])}
                for p in self.pending
            ],
            "sources": sources,
            "errors": list(self.report.errors),
        }
