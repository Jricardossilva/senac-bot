"""Modelos do Gerenciador de Eventos: evento, fonte e item de conhecimento (camada 2).

Cada evento tem a sua própria base; nada é compartilhado entre eventos. Informação só chega ao visitante quando o item
está CONFIRMADO (aprovado pelo operador ou confirmado automaticamente por regra de confiabilidade).
"""
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any

# Ciclo de vida do evento
EVENT_STATES = ("draft", "prepared", "active", "inactive", "archived")
STATE_LABELS = {
    "draft": "Rascunho", "prepared": "Preparado",
    "active": "Ativo", "inactive": "Inativo", "archived": "Arquivado",
}

# Estados de cada informação (item)
ITEM_STATUSES = ("found", "confirmed", "pending", "divergent", "stale", "rejected")
STATUS_LABELS = {
    "found": "Encontrada", "confirmed": "Confirmada", "pending": "Aguardando validação",
    "divergent": "Divergente", "stale": "Desatualizada", "rejected": "Rejeitada",
}
VISIBLE_STATUSES = ("confirmed",)  # só isso chega ao visitante

CATEGORIES = (
    "about", "objectives", "organization", "location", "dates", "schedule", "activities", "speakers",
    "exhibitors", "visitor_info", "faq", "news", "updates",
)
CATEGORY_LABELS = {
    "about": "Sobre o evento", "objectives": "Objetivos", "organization": "Organização", "location": "Localização",
    "dates": "Datas e horários", "schedule": "Programação", "activities": "Atividades, oficinas e competições",
    "speakers": "Palestrantes e participantes", "exhibitors": "Expositores", "visitor_info": "Informações para visitantes",
    "faq": "Perguntas frequentes", "news": "Notícias", "updates": "Atualizações",
}

SOURCE_TRUST = ("official", "candidate", "third_party")  # oficial (declarada pelo operador), candidata (descoberta), terceiros
SOURCE_ORIGINS = ("operator", "discovered")
MAX_ITEM_WORDS = 90  # texto falável, como na base institucional


@dataclass
class EventSource:
    id: str
    url: str
    kind: str = "site"  # site | program | social | document | other
    trust: str = "official"
    origin: str = "operator"
    title: str = ""
    last_checked: str | None = None
    last_ok: str | None = None
    error: str | None = None
    hash: str | None = None
    failures: int = 0
    note: str = ""


@dataclass
class EventItem:
    id: str
    category: str
    title: str
    content: str  # trecho literal da fonte (ou texto editado pelo operador)
    source_ids: list[str] = field(default_factory=list)
    status: str = "pending"
    approved_by: str | None = None  # "operator" | "auto" | None
    found_at: str = ""
    updated_at: str = ""
    valid_until: str | None = None  # AAAA-MM-DD
    keywords: list[str] = field(default_factory=list)
    key_facts: dict[str, Any] = field(default_factory=dict)  # datas/horários extraídos (para detectar divergência e mudança)
    note: str = ""
    edited: bool = False  # conteúdo ajustado pelo operador: nunca é sobrescrito por pesquisa
    history: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Event:
    id: str
    name: str
    area: str
    description: str
    start_date: str  # AAAA-MM-DD
    end_date: str
    state: str = "draft"
    organization: str = ""
    city: str = ""
    uf: str = ""
    venue: str = ""
    website: str = ""
    program_url: str = ""
    social: list[str] = field(default_factory=list)
    objective: str = ""
    audience: str = ""
    notes: str = ""
    keywords: list[str] = field(default_factory=list)
    reference_documents: list[str] = field(default_factory=list)
    welcome: str = ""  # mensagem de boas-vindas personalizada (opcional)
    suggested_questions: list[str] = field(default_factory=list)
    simulation: bool = False  # cadastro fictício de teste, identificado como simulação
    auto_approve_official: bool = True  # confirma automaticamente trechos literais de fontes oficiais
    update_interval_hours: int = 0  # 0 = sem atualização programada
    created_at: str = ""
    updated_at: str = ""
    last_prepared_at: str | None = None
    last_updated_at: str | None = None
    last_scheduled_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def period(self) -> tuple[date | None, date | None]:
        def parse(value: str) -> date | None:
            try:
                return date.fromisoformat(value)
            except ValueError:
                return None
        return parse(self.start_date), parse(self.end_date)
