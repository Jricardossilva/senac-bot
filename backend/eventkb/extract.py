"""Extração de conteúdo de páginas de eventos: blocos de texto LITERAIS, classificados por categoria.

Não há resumo nem reescrita automática: o que o visitante ouve é um trecho que a fonte realmente publica (ou o texto que
o operador editou). Datas e horários são extraídos à parte, só para comparar fontes e detectar mudanças.
"""
import hashlib
import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

from backend.eventkb.models import MAX_ITEM_WORDS
import unicodedata

from backend.knowledge.text import normalize

MIN_BLOCK_CHARS = 30
MAX_BLOCKS_PER_PAGE = 80
BLOCK_TAGS = {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "td", "th", "dd", "dt", "blockquote", "figcaption", "summary", "div", "section", "article"}
HEADING_TAGS = {"h1", "h2", "h3", "h4"}
SKIP_TAGS = {"script", "style", "noscript", "template", "svg", "head", "nav", "footer", "form", "button", "select", "iframe"}
BOILERPLATE = re.compile(r"cookies?|politica de privacidade|todos os direitos|termos de uso|compartilh|fale conosco|siga-nos|newsletter|copyright|lgpd", re.I)

MONTHS = {"janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4, "maio": 5, "junho": 6, "julho": 7, "agosto": 8,
          "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12}
_MONTHS_RX = "|".join(MONTHS)
_DATE_NUMERIC = re.compile(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b")
_DATE_LONG = re.compile(rf"\b(\d{{1,2}})\s*(?:de\s+)?({_MONTHS_RX})(?:\s+de\s+(\d{{4}}))?\b")
_DATE_RANGE = re.compile(rf"\b(\d{{1,2}})\s*(?:a|ao|e|até|-)\s*(\d{{1,2}})\s+de\s+({_MONTHS_RX})(?:\s+de\s+(\d{{4}}))?\b")
_TIME = re.compile(r"\b(\d{1,2})\s*(?:h|:)\s*(\d{2})?\b")
_CANCEL = re.compile(r"\b(cancelad[oa]s?|adiad[oa]s?|suspens[oa]s?|remarcad[oa]s?|transferid[oa]s?|nao havera)\b")

# categoria -> padrões (sobre texto normalizado); a primeira que casar com mais força vence
CATEGORY_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("faq", re.compile(r"perguntas frequentes|duvidas frequentes|\bfaq\b|\?$")),
    ("speakers", re.compile(r"palestrante|palestra de|convidad[oa]|speaker|ministrad[oa] por|mediacao|painelista|participantes? confirmad")),
    ("schedule", re.compile(r"programacao|cronograma|agenda|\bgrade\b|\bhorarios?\b|\b\d{1,2}\s*(?:h\d{0,2}|:\d{2})")),
    ("activities", re.compile(r"oficina|workshop|competicao|torneio|desafio|minicurso|atividade|demonstracao|campeonato|maratona")),
    ("exhibitors", re.compile(r"expositor|exposicao|\bstands?\b|estande|patrocin|parceiros?|empresas participantes")),
    ("visitor_info", re.compile(r"visit|ingresso|entrada (?:gratuita|livre)|estacionamento|acessibilidade|como chegar|credenciamento|inscri[cs]|publico|gratuit")),
    ("location", re.compile(r"endereco|\blocal\b|onde (?:sera|fica|acontece)|\bauditorio\b|\bginasio\b|\bavenida\b|\bav\.|\brua\b|\bcampus\b|centro de educacao")),
    ("objectives", re.compile(r"objetivo|proposito|finalidade|missao|nosso foco")),
    ("organization", re.compile(r"organiza[cd]|realizacao|realiza[cd]|promocao|apoio institucional|coordenacao")),
    ("news", re.compile(r"noticia|novidade|comunicado|imprensa")),
    ("dates", re.compile(r"\bdatas?\b|periodo|de \d{1,2} a \d{1,2}|\d{1,2}/\d{1,2}|\b(?:" + _MONTHS_RX + r")\b")),
]


def fold(text: str) -> str:
    """Minúsculas e sem acentos, MANTENDO a pontuação (datas como 24/11 e horários como 14:30 dependem dela)."""
    decomposed = unicodedata.normalize("NFKD", str(text).casefold())
    return " ".join("".join(c for c in decomposed if not unicodedata.combining(c)).split())


@dataclass
class Block:
    heading: str
    text: str
    category: str = "about"
    facts: dict = field(default_factory=dict)
    cancelled: bool = False
    truncated: bool = False


@dataclass
class ParsedPage:
    title: str = ""
    description: str = ""
    blocks: list[Block] = field(default_factory=list)
    structured: list[dict] = field(default_factory=list)  # eventos em JSON-LD (schema.org)
    text: str = ""  # texto corrido da página (para identificar o evento e para o snapshot)
    links: list[tuple[str, str]] = field(default_factory=list)  # (texto do link, href)


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.description = ""
        self.jsonld: list[str] = []
        self.blocks: list[tuple[str, str]] = []  # (heading, text)
        self._skip = 0
        self._in_title = False
        self._in_jsonld = False
        self._jsonld_buf: list[str] = []
        self._buf: list[str] = []
        self._stack: list[str] = []
        self._heading = ""
        self._in_heading = False
        self.links: list[tuple[str, str]] = []
        self._link_href: str | None = None
        self._link_text: list[str] = []
        self._link_chars = 0

    def _flush(self) -> None:
        text = " ".join(" ".join(self._buf).split())
        only_links = bool(text) and self._link_chars / max(len(text), 1) > 0.7
        self._buf, self._link_chars = [], 0
        if not text or only_links:
            return
        if self._in_heading:
            self._heading = text
        else:
            self.blocks.append((self._heading, text))

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "meta" and (attributes.get("name") or attributes.get("property") or "").lower() in ("description", "og:description"):
            self.description = self.description or (attributes.get("content") or "").strip()
        if tag == "script" and "ld+json" in (attributes.get("type") or "").lower():
            self._in_jsonld, self._jsonld_buf = True, []
            return
        if tag == "title":
            self._in_title = True
        if tag in SKIP_TAGS:
            self._skip += 1
            return
        if tag in BLOCK_TAGS:
            self._flush()
            self._in_heading = tag in HEADING_TAGS
            self._stack.append(tag)
        if tag == "br":
            self._buf.append(" ")
        if tag == "a" and attributes.get("href"):
            self._link_href, self._link_text = attributes["href"], []

    def handle_endtag(self, tag):
        if tag == "a" and self._link_href is not None:
            self.links.append((" ".join(" ".join(self._link_text).split()), self._link_href))
            self._link_href = None
        if tag == "script" and self._in_jsonld:
            self._in_jsonld = False
            self.jsonld.append("".join(self._jsonld_buf))
            return
        if tag == "title":
            self._in_title = False
        if tag in SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
            return
        if tag in BLOCK_TAGS:
            self._flush()
            self._in_heading = False
            if tag in self._stack:
                self._stack.remove(tag)

    def handle_data(self, data):
        if self._in_jsonld:
            self._jsonld_buf.append(data)
        elif self._in_title:
            self.title += data
        elif not self._skip and data.strip():
            self._buf.append(data.strip())
            if self._link_href is not None:
                self._link_text.append(data.strip())
                self._link_chars += len(data.strip()) + 1

    def close(self):
        super().close()
        self._flush()


def parse_page(html: str) -> ParsedPage:
    parser = _PageParser()
    parser.feed(html)
    parser.close()
    structured: list[dict] = []
    for raw in parser.jsonld:
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        for node in (data if isinstance(data, list) else [data]):
            if isinstance(node, dict) and str(node.get("@type", "")).lower().endswith("event"):
                structured.append(node)
    blocks = [(h, t) for h, t in parser.blocks]
    text = " ".join([parser.title, parser.description] + [t for _, t in blocks])
    page = ParsedPage(" ".join(parser.title.split()), " ".join(parser.description.split()), [], structured, " ".join(text.split()), parser.links)
    blocks = _join_questions(blocks)
    seen: set[str] = set()
    for heading, body in blocks:
        norm = normalize(body)
        if len(body) < MIN_BLOCK_CHARS or norm in seen or BOILERPLATE.search(norm):
            continue
        seen.add(norm)
        page.blocks.append(make_block(heading, body))
        if len(page.blocks) >= MAX_BLOCKS_PER_PAGE:
            break
    return page


def _join_questions(blocks: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Pergunta curta seguida de resposta (mesmo título) vira um item único: 'Pergunta? Resposta.'"""
    out: list[tuple[str, str]] = []
    i = 0
    while i < len(blocks):
        heading, text = blocks[i]
        if text.rstrip().endswith("?") and len(text.split()) <= 30 and i + 1 < len(blocks) and blocks[i + 1][0] == heading:
            out.append((heading or "Perguntas frequentes", f"{text} {blocks[i + 1][1]}"))
            i += 2
            continue
        out.append((heading, text))
        i += 1
    return out


def _truncate(text: str) -> tuple[str, bool]:
    words = text.split()
    if len(words) <= MAX_ITEM_WORDS:
        return text, False
    kept: list[str] = []
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        n = len(sentence.split())
        if kept and len(" ".join(kept).split()) + n > MAX_ITEM_WORDS:
            break
        kept.append(sentence)
    out = " ".join(kept)
    if len(out.split()) > MAX_ITEM_WORDS:
        out = " ".join(words[:MAX_ITEM_WORDS])
    return out, True


def make_block(heading: str, text: str) -> Block:
    clipped, truncated = _truncate(text)
    block = Block(heading=heading.strip(), text=clipped, truncated=truncated)
    block.category = classify(heading, clipped)
    block.facts = extract_facts(clipped)
    block.cancelled = bool(_CANCEL.search(fold(clipped)))
    return block


BODY_ONLY_IF_TIMED = {"schedule": re.compile(r"\bdia \d{1,2}\b.*\b\d{1,2}\s*(?:h\d{0,2}|:\d{2})|\b\d{1,2}\s*(?:h\d{0,2}|:\d{2})\b")}


def classify(heading: str, text: str) -> str:
    """Categoria do bloco: o título pesa mais que o corpo; sem pista, 'about'."""
    head, body = fold(heading), fold(text)
    for category, pattern in CATEGORY_PATTERNS:
        if head and pattern.search(head):
            return category
    best, best_rank = "about", 99
    for rank, (category, pattern) in enumerate(CATEGORY_PATTERNS):
        body_pattern = BODY_ONLY_IF_TIMED.get(category, pattern)
        if body_pattern.search(body) and rank < best_rank:
            best, best_rank = category, rank
    if best == "faq" and not text.strip().endswith("?") and "perguntas" not in head:
        best = next((c for c, p in CATEGORY_PATTERNS if c != "faq" and p.search(body)), "about")
    return best


def extract_facts(text: str, default_year: int | None = None) -> dict:
    """Datas (AAAA-MM-DD) e horários (HH:MM) literais do texto, para comparar fontes e detectar mudanças."""
    norm = fold(text)
    dates: set[str] = set()
    for m in _DATE_RANGE.finditer(norm):
        year = int(m.group(4) or default_year or 0)
        month = MONTHS[m.group(3)]
        for day in (m.group(1), m.group(2)):
            dates.add(_iso(year, month, int(day)))
    for m in _DATE_LONG.finditer(norm):
        year = int(m.group(3) or default_year or 0)
        dates.add(_iso(year, MONTHS[m.group(2)], int(m.group(1))))
    for m in _DATE_NUMERIC.finditer(norm):
        day, month = int(m.group(1)), int(m.group(2))
        year = int(m.group(3)) if m.group(3) else (default_year or 0)
        if year and year < 100:
            year += 2000
        if 1 <= month <= 12 and 1 <= day <= 31:
            dates.add(_iso(year, month, day))
    times = {f"{int(m.group(1)):02d}:{int(m.group(2) or 0):02d}" for m in _TIME.finditer(norm) if int(m.group(1)) < 24 and int(m.group(2) or 0) < 60}
    facts: dict = {}
    if dates:
        facts["dates"] = sorted(dates)
    if times:
        facts["times"] = sorted(times)
    return facts


def _iso(year: int, month: int, day: int) -> str:
    return f"{year:04d}-{month:02d}-{day:02d}" if year else f"----{month:02d}-{day:02d}"  # sem ano: só mês-dia


def content_fingerprint(text: str) -> str:
    return hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()
