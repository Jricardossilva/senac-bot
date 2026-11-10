"""Catálogo de ofertas usado na orientação de cursos (knowledge/offers.json).

Cada oferta é um fato público citado por uma página oficial: nome/área, unidade que a página confirma (ou nenhuma),
modalidade e frase curta para fala. Preço, carga horária, datas, horários, vagas e requisitos NÃO existem aqui:
só a programação oficial os traz.
"""
import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from backend.knowledge.models import FRESHNESS, STATUSES, Source

logger = logging.getLogger("senac_bot.knowledge.offers")

EAD_UNIT = "EAD"
CEP_JP = "CEP-JP"
KINDS = ("curso", "area", "ead")
MODALITIES = ("nao_informada", "ead", "movel")
MAX_PHRASE_WORDS = 30
MAX_PITCH_WORDS = 32


@dataclass(frozen=True)
class Offer:
    id: str
    kind: str
    unit: str | None  # chave da unidade (aliases.json), "EAD" ou None quando a página não informa a unidade
    modality: str
    phrase: str
    pitch: str
    keywords: tuple[str, ...]
    refine: tuple[str, ...]
    source_ids: tuple[str, ...]
    evidence: tuple[str, ...]
    consulted_at: date
    valid_until: date | None
    freshness: str
    status: str

    @property
    def tier(self) -> int:
        """1 = CEP-JP; 2 = demais unidades do Senac Paraíba (inclui oferta sem unidade informada); 3 = Senac EAD."""
        if self.unit == CEP_JP:
            return 1
        if self.unit == EAD_UNIT:
            return 3
        return 2

    @property
    def unit_known(self) -> bool:
        return self.unit is not None and self.unit != EAD_UNIT


@dataclass(frozen=True)
class Area:
    id: str
    keywords: tuple[str, ...]
    opener: str
    clarify: str
    segment: str = ""  # segmento da grade do portal (ex.: "Tecnologia da informação"): turmas "vizinhas" quando não há do assunto exato


@dataclass
class OfferCatalog:
    offers: list[Offer] = field(default_factory=list)
    areas: list[Area] = field(default_factory=list)
    generic_prompt: str = "Em qual área você tem mais interesse?"
    errors: list[str] = field(default_factory=list)

    def get(self, offer_id: str) -> Offer | None:
        return next((o for o in self.offers if o.id == offer_id), None)


def _date(value: object, label: str, errors: list[str], required: bool = True) -> date | None:
    if value in (None, ""):
        if required:
            errors.append(f"{label}: data obrigatória")
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        errors.append(f"{label}: data inválida {value!r}")
        return None


def _build_offer(item: dict, sources: dict[str, Source], unit_keys: set[str], errors: list[str]) -> Offer | None:
    oid = str(item.get("id", "")).strip()
    label = f"offers.json[{oid or '?'}]"
    problems = len(errors)
    if not oid:
        errors.append("offers.json: oferta sem id")
        return None
    kind, modality, status, freshness = item.get("kind"), item.get("modality"), item.get("status"), item.get("freshness")
    if kind not in KINDS:
        errors.append(f"{label}: kind inválido {kind!r}")
    if modality not in MODALITIES:
        errors.append(f"{label}: modality inválida {modality!r}")
    if status not in STATUSES:
        errors.append(f"{label}: status inválido {status!r}")
    if freshness not in FRESHNESS:
        errors.append(f"{label}: freshness inválido {freshness!r}")
    unit = item.get("unit")
    if unit is not None and unit != EAD_UNIT and unit not in unit_keys:
        errors.append(f"{label}: unidade inexistente {unit!r}")
    if (modality == "ead") != (unit == EAD_UNIT):
        errors.append(f"{label}: modalidade EAD e unidade 'EAD' devem andar juntas")
    phrase, pitch = str(item.get("phrase", "")).strip(), str(item.get("pitch", "")).strip()
    if not phrase or len(phrase.split()) > MAX_PHRASE_WORDS:
        errors.append(f"{label}: 'phrase' vazia ou com mais de {MAX_PHRASE_WORDS} palavras")
    if not pitch or len(pitch.split()) > MAX_PITCH_WORDS:
        errors.append(f"{label}: 'pitch' vazio ou com mais de {MAX_PITCH_WORDS} palavras")
    keywords = tuple(str(k) for k in item.get("keywords", []))
    if not keywords:
        errors.append(f"{label}: sem palavras-chave")
    source_ids = tuple(item.get("source_ids", []))
    if not source_ids:
        errors.append(f"{label}: sem fonte oficial")
    for source_id in source_ids:
        if source_id not in sources:
            errors.append(f"{label}: fonte inexistente {source_id!r}")
    evidence = tuple(str(e) for e in item.get("evidence", []))
    if not evidence:
        errors.append(f"{label}: sem 'evidence' (trecho literal da página oficial)")
    consulted = _date(item.get("consulted_at"), f"{label}.consulted_at", errors)
    valid_until = _date(item.get("valid_until"), f"{label}.valid_until", errors, required=False)
    if len(errors) > problems or consulted is None:
        return None
    return Offer(
        id=oid, kind=kind, unit=unit, modality=modality, phrase=phrase, pitch=pitch, keywords=keywords,
        refine=tuple(str(r) for r in item.get("refine", [])), source_ids=source_ids, evidence=evidence,
        consulted_at=consulted, valid_until=valid_until, freshness=freshness, status=status,
    )


def load_offers(directory: Path, sources: dict[str, Source], unit_keys: set[str], load_json) -> OfferCatalog:
    """Carrega knowledge/offers.json. Problemas viram erros do catálogo; nunca derrubam a aplicação."""
    catalog = OfferCatalog()
    try:
        raw = load_json(directory / "offers.json")
    except FileNotFoundError:
        return catalog  # sem catálogo: a orientação de cursos fica desativada
    except (OSError, ValueError) as error:
        catalog.errors.append(f"offers.json não lido: {error}")
        return catalog
    seen: set[str] = set()
    for item in raw.get("offers", []):
        offer = _build_offer(item, sources, unit_keys, catalog.errors)
        if offer is None:
            continue
        if offer.id in seen:
            catalog.errors.append(f"offers.json: id duplicado {offer.id!r}")
            continue
        seen.add(offer.id)
        catalog.offers.append(offer)
    for item in raw.get("areas", []):
        try:
            catalog.areas.append(Area(str(item["id"]), tuple(item["keywords"]), str(item["opener"]), str(item["clarify"]), str(item.get("segment", ""))))
        except (KeyError, TypeError) as error:
            catalog.errors.append(f"offers.json: área inválida ({error})")
    if raw.get("generic_prompt"):
        catalog.generic_prompt = str(raw["generic_prompt"])
    for problem in catalog.errors:
        logger.error("Catálogo de ofertas: %s", problem)
    return catalog
