"""Modelos da base de conhecimento institucional."""
from dataclasses import dataclass, field
from datetime import date

CATEGORIES = ("permanent", "units", "courses", "programs", "social", "empresas", "news_events", "faq")
LEVELS = ("brasil", "paraiba", "cep-jp")
STATUSES = ("verified", "review", "pending")
FRESHNESS = ("permanent", "periodic", "volatile")
NATURES = ("permanent", "historical", "open", "unconfirmed")  # ação permanente, fato histórico, vigente (confirmado), sem confirmação
KINDS = ("institutional", "general", "guidance")  # general = conteúdo educativo do projeto (não é fato institucional)

# Situação efetiva (calculada): ordem de gravidade usada na resposta.
EFFECTIVE = ("pending", "stale", "review", "verified")

LEVEL_LABELS = {
    "brasil": "Senac Brasil",
    "paraiba": "Senac Paraíba",
    "cep-jp": "CEP João Pessoa (CEP-JP)",
}


@dataclass(frozen=True)
class Source:
    id: str
    name: str
    url: str
    level: str
    freshness: str
    dynamic: bool = False
    expect: tuple[str, ...] = ()
    min_length: int = 0
    noisy: bool = False  # página que muda o tempo todo (home, notícias): mudança não exige revisão
    category: str = ""  # ex.: "Cursos e matrículas" (organização no painel do operador)
    institution: str = ""  # ex.: "Senac PB"
    kind: str = "official"  # tipo da fonte: sempre oficial na base institucional


@dataclass(frozen=True)
class Entry:
    id: str
    title: str
    content: str
    category: str
    level: str
    unit: str | None
    kind: str
    keywords: tuple[str, ...]
    questions: tuple[str, ...]
    source_ids: tuple[str, ...]
    consulted_at: date
    valid_until: date | None
    freshness: str
    status: str
    short: str | None = None
    nature: str | None = None
    unit_note: str | None = None
    notes: str | None = None
    url: str | None = None
    source_note: str | None = None


@dataclass
class LoadReport:
    """Resultado do carregamento: entradas válidas e problemas encontrados (nunca derruba a aplicação)."""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
