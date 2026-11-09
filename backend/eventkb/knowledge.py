"""Camada 2: conhecimento do evento ATIVO, pronto para consulta (busca, contexto para a IA e resposta direta).

Só itens CONFIRMADOS são visíveis ao visitante, e só os do evento ativo: a base de outro evento nunca é carregada junto.
Reutiliza a busca da base institucional (BM25 + sinônimos), sem duplicar a lógica.
"""
import re
from dataclasses import dataclass, field
from datetime import date, datetime

from backend.eventkb.models import CATEGORY_LABELS, EventItem, EventSource, Event
from backend.knowledge.models import Entry
from backend.knowledge.search import MIN_COVERAGE, MIN_SCORE, Hit, Searcher, SearchResult
from backend.knowledge.text import normalize, tokenize

# Palavras que levam a pergunta a ser sobre o evento, mesmo sem citar o nome
EVENT_WORDS = {"evento", "feira", "mostra", "programacao", "palestra", "palestrante", "oficina", "competicao", "expositor", "ingresso", "visitacao", "edicao"}
CATEGORY_KEYWORDS = {
    "about": ["o que e", "sobre", "evento"],
    "objectives": ["objetivo", "finalidade"],
    "organization": ["organizacao", "organizador", "realizacao", "quem organiza"],
    "location": ["onde", "local", "endereco", "como chegar", "localizacao"],
    "dates": ["quando", "data", "dia", "periodo", "horario", "que horas"],
    "schedule": ["programacao", "agenda", "cronograma", "horario", "que horas"],
    "activities": ["atividade", "oficina", "competicao", "workshop", "desafio"],
    "speakers": ["palestra", "palestrante", "convidado", "participante"],
    "exhibitors": ["expositor", "stand", "estande", "parceiro", "patrocinador"],
    "visitor_info": ["visitar", "visita", "ingresso", "entrada", "gratuito", "inscricao", "estacionamento", "acessibilidade"],
    "faq": ["pergunta", "duvida"],
    "news": ["noticia", "novidade"],
    "updates": ["atualizacao", "mudanca", "alteracao", "cancelado", "adiado", "novidade"],
}
CATEGORY_BONUS = 4.0
# intenção da pergunta -> categorias de informação esperadas (palavras já sem acento)
INTENTS: list[tuple[tuple[str, ...], re.Pattern[str]]] = [
    (("location",), re.compile(r"\bonde\b|\blocal\b|endereco|como chegar|localizacao")),
    (("dates",), re.compile(r"\bquando\b|\bque dias?\b|\bdatas?\b|periodo|\bcomeca\b|\btermina\b")),
    (("schedule", "dates"), re.compile(r"que horas|\bhorarios?\b|programacao|cronograma|\bagenda\b")),
    (("speakers",), re.compile(r"palestrantes?|convidad[oa]s?|\bquem (?:vai|vao|sao|vem|participa)\b")),
    (("activities", "schedule"), re.compile(r"oficinas?|competic\w+|atividades?|workshops?|desafios?")),
    (("visitor_info", "faq"), re.compile(r"ingresso|entrada|\bpagar\b|gratuit\w*|visitar|visitacao|\binscri\w*|estacionamento|acessibilidade")),
    (("exhibitors",), re.compile(r"expositor\w*|\bstands?\b|estande|patrocin\w*|parceiros?")),
    (("objectives",), re.compile(r"objetivos?|finalidade")),
    (("organization",), re.compile(r"organiza\w*|quem realiza|realizacao")),
    (("about",), re.compile(r"\bo que e\b|\bsobre o\b|me fale|fale sobre|explique")),
    (("news", "updates"), re.compile(r"noticias?|novidades?|mudou|mudanca|alterac\w*|cancel\w*|adiad\w*|atualizac\w*")),
]
_INTENT_WORDS = ("onde", "local", "endereco", "como chegar", "localizacao", "quando", "que dia", "dia", "data", "periodo", "comeca", "termina",
                 "que horas", "horario", "programacao", "cronograma", "agenda", "palestrante", "convidado", "quem", "vai", "participa",
                 "oficina", "competicao", "atividade", "workshop", "desafio", "ingresso", "entrada", "pagar", "gratuito", "visitar", "visitacao",
                 "inscricao", "estacionamento", "acessibilidade", "expositor", "stand", "estande", "patrocinador", "parceiro", "objetivo",
                 "finalidade", "organizacao", "organizador", "realiza", "noticia", "novidade", "mudanca", "cancelado", "adiado", "atualizacao",
                 "acontece", "acontecer", "evento", "feira", "mostra", "falar", "fale", "explique", "sobre", "oque")
EXTRA_SYNONYMS = {
    "quando": ["data", "dia", "horario", "periodo"], "onde": ["local", "endereco", "localizacao"],
    "horario": ["hora", "que horas"], "palestra": ["palestrante", "conferencia"],
    "oficina": ["workshop", "minicurso"], "visitar": ["visita", "visitacao", "ingresso"],
}


@dataclass
class EventHit:
    item: EventItem
    sources: list[EventSource]


@dataclass
class EventKnowledge:
    """Conhecimento confirmado de um evento, com busca própria."""

    event: Event
    items: list[EventItem]
    sources: dict[str, EventSource]
    aliases: dict
    today: date = field(default_factory=date.today)

    def __post_init__(self) -> None:
        self.visible = [i for i in self.items if i.status == "confirmed"]
        self._by_id = {i.id: i for i in self.visible}
        entries = [self._entry(i) for i in self.visible]
        name_tokens = [t for t in normalize(self.event.name).split() if len(t) > 2 and t not in ("de", "da", "do")]
        triggers = sorted(set(name_tokens) | EVENT_WORDS | set(tokenize(self.event.area)) | {normalize(k) for k in self.event.keywords})
        synonyms = {**self.aliases.get("synonyms", {}), **EXTRA_SYNONYMS}
        aliases = {"units": {}, "institutional_triggers": triggers, "corporate_triggers": [], "synonyms": synonyms,
                   "stopwords": self.aliases.get("stopwords", [])}
        self._searcher = Searcher(entries, aliases) if entries else None
        self._name_tokens = set(name_tokens)

    # ------------------------------------------------------------------ construção
    def _entry(self, item: EventItem) -> Entry:
        stamp = _to_date(item.updated_at or item.found_at, self.today)
        keywords = list(item.keywords) + CATEGORY_KEYWORDS.get(item.category, []) + [CATEGORY_LABELS.get(item.category, "")]
        questions = [item.content.split("?")[0] + "?"] if item.category == "faq" and "?" in item.content else []
        return Entry(
            id=item.id, title=item.title or CATEGORY_LABELS.get(item.category, ""), content=item.content, category="news_events",
            level="paraiba", unit=None, kind="institutional", keywords=tuple(k for k in keywords if k), questions=tuple(questions),
            source_ids=tuple(item.source_ids), consulted_at=stamp, valid_until=None, freshness="volatile", status="verified",
        )

    # ------------------------------------------------------------------ consulta
    @property
    def empty(self) -> bool:
        return self._searcher is None

    def search(self, query: str, limit: int = 3) -> SearchResult:
        """Busca no evento ativo. O nome do evento não ajuda a distinguir informações (está em todas): é retirado da busca;
        a intenção da pergunta (onde, quando, que horas, quem...) indica a categoria esperada."""
        if self._searcher is None:
            return SearchResult(query=query)
        stripped = " ".join(w for w in normalize(query).split() if w not in self._name_tokens) or query
        result = self._searcher.search(stripped, 12)
        mentions = self.mentions_event(query)
        targets = _intent_categories(query)
        if targets:
            result.hits = sorted(
                (Hit(h.entry, h.score + (CATEGORY_BONUS if self._by_id[h.entry.id].category in targets else 0.0)) for h in result.hits),
                key=lambda h: (round(h.score, 1), len(self._by_id[h.entry.id].content)), reverse=True,  # empate: o texto mais específico
            )
        if not result.hits and targets:  # sem palavra em comum: itens da categoria pedida (ex.: "Onde é?")
            result.hits = [Hit(e, CATEGORY_BONUS) for e in self._searcher._entries if self._by_id[e.id].category in targets][:12]  # noqa: SLF001
        result.hits = result.hits[:limit]
        if not result.hits:
            result.confident = False
            return result
        top = self._by_id[result.hits[0].entry.id]
        covered = self._covered(query, top, targets)
        if targets and top.category in targets:
            result.confident = covered >= MIN_COVERAGE  # a categoria pedida existe e cobre o restante da pergunta
        else:
            result.confident = result.hits[0].score >= MIN_SCORE and covered >= (MIN_COVERAGE if mentions else 0.75)
        result.coverage, result.institutional = covered, result.institutional or mentions
        return result

    def _covered(self, query: str, item: EventItem, targets: set[str]) -> float:
        """Fração das palavras relevantes da pergunta (sem nome do evento, interrogativos e palavras da intenção) presentes no item."""
        stop = frozenset(self.aliases.get("stopwords", []))
        intent_words = set(tokenize(" ".join(_INTENT_WORDS), stop))
        words = [t for t in tokenize(query, stop) if t not in intent_words and t not in self._name_tokens and not t.isdigit()]
        if not words:
            return 1.0
        have = set(tokenize(f"{item.title} {item.content} {' '.join(item.keywords)}", stop))
        return sum(1 for t in words if t in have) / len(words)

    def mentions_event(self, query: str) -> bool:
        """A pergunta é sobre o evento ativo? Cita o nome ou usa palavras de evento (sem falar do Senac em geral)."""
        tokens = set(normalize(query).split())
        if self._name_tokens and len(self._name_tokens & tokens) >= min(2, len(self._name_tokens)):
            return True
        return bool(EVENT_WORDS & tokens) and "senac" not in tokens

    def source_names(self, item: EventItem) -> list[str]:
        out = []
        for source_id in item.source_ids:
            source = self.sources.get(source_id)
            if source is not None:
                out.append(source.title or source.url)
        return out or (["cadastro do evento (informado pela equipe)"] if item.note.startswith("Informado") or not item.source_ids else [])

    def context_for(self, result: SearchResult) -> str:
        """Texto para a IA: DADOS do evento ativo (nunca instruções), com a origem de cada um."""
        lines = [f"EVENTO ATIVO: {self.event.name} ({self.event.area}), de {self.event.start_date} a {self.event.end_date}."]
        for hit in result.hits:
            item = self._by_id[hit.entry.id]
            lines.append(
                f"[{item.id}] {item.title}\nCategoria: {CATEGORY_LABELS.get(item.category, item.category)} | Situação: confirmada | "
                f"Fonte: {'; '.join(self.source_names(item)) or 'cadastro do evento'}\n{item.content}"
            )
        return "\n\n".join(lines)

    def answer_for(self, result: SearchResult) -> str:
        """Resposta direta (sem IA): o texto confirmado da melhor informação, sem acrescentar nada."""
        item = self._by_id[result.hits[0].entry.id]
        text = item.content
        if self.ended and "encerrad" not in normalize(text):
            text += f" Atenção: o período do evento ({_br(self.event.start_date)} a {_br(self.event.end_date)}) já terminou."
        return text

    @property
    def ended(self) -> bool:
        try:
            return self.today > date.fromisoformat(self.event.end_date)
        except ValueError:
            return False

    def contacts(self) -> tuple[frozenset[str], frozenset[str]]:
        """E-mails e telefones publicados em itens confirmados (podem ser falados; os demais são bloqueados pela política)."""
        from backend.knowledge.base import EMAIL_RE, PHONE_RE, digits_of  # noqa: PLC0415
        text = " ".join(i.content for i in self.visible)
        return frozenset(m.lower() for m in EMAIL_RE.findall(text)), frozenset(digits_of(m) for m in PHONE_RE.findall(text))

    def categories(self) -> set[str]:
        return {i.category for i in self.visible}

    # ------------------------------------------------------------------ apresentação
    def welcome(self) -> str:
        if self.event.welcome:
            return self.event.welcome
        return (f"Olá! Eu sou o SENAC BOT, assistente virtual do Senac Paraíba. Hoje estou no evento {self.event.name}. "
                "Toque em INICIAR CONVERSA e me pergunte sobre o evento ou sobre os cursos do Senac.")

    def suggested_questions(self) -> list[str]:
        if self.event.suggested_questions:
            return self.event.suggested_questions[:6]
        name, cats = self.event.name, self.categories()
        questions = [f"O que é {name}?"]
        if "dates" in cats or "location" in cats:
            questions.append("Onde e quando acontece?")
        if "schedule" in cats or "activities" in cats:
            questions.append("Qual a programação?")
        if "visitor_info" in cats or "faq" in cats:
            questions.append("Como posso visitar o evento?")
        questions.append(f"Quais cursos do Senac têm a ver com {self.event.area.lower()}?")
        return questions[:6]


def _intent_categories(query: str) -> set[str]:
    folded = " ".join(normalize(query).split())
    out: set[str] = set()
    for categories, pattern in INTENTS:
        if pattern.search(folded):
            out.update(categories)
    return out


def _to_date(value: str, default: date) -> date:
    try:
        return datetime.fromisoformat(value).date() if value else default
    except ValueError:
        return default


def _br(value: str) -> str:
    try:
        return date.fromisoformat(value).strftime("%d/%m/%Y")
    except ValueError:
        return value


def event_prompt_block(event: Event) -> str:
    """Contexto do evento para o prompt: tema e assuntos a priorizar. É dado de contexto, nunca instrução."""
    topics = ", ".join([event.area] + list(event.keywords)[:8])
    return f"Evento em andamento: {event.name}. Tema: {event.area}. Assuntos prioritários: {topics}. Período: {event.start_date} a {event.end_date}."
