"""Busca na base de conhecimento: BM25 com campos ponderados, sinônimos e desambiguação de unidade.

Regras de segurança:
 - se a pergunta cita uma unidade (ex.: CEP-JP), entradas de OUTRAS unidades são excluídas dos resultados;
 - entradas gerais (sem unidade) continuam elegíveis, mas o chamador recebe `unit` para avisar que a
   informação é geral e não confirma que pertença àquela unidade.
"""
import math
from dataclasses import dataclass, field

from backend.knowledge.models import Entry
from backend.knowledge.text import contains_sequence, normalize, stem, tokenize

K1 = 1.2
B = 0.75
FIELD_WEIGHTS = {"title": 3.0, "keywords": 3.0, "questions": 2.0, "content": 1.0}
MIN_SCORE = 3.2  # abaixo disso a base não "tem" a informação
MIN_COVERAGE_GENERAL = 0.75  # perguntas sem assunto institucional exigem mais cobertura
MIN_COVERAGE = 0.5  # fração (ponderada por raridade) dos termos da pergunta que a melhor entrada cobre
CORPORATE_TOKENS = {"empresa", "empresario", "empresaria", "colaborador", "funcionario", "sindicato", "corporativo", "rh"}


@dataclass(frozen=True)
class Hit:
    entry: Entry
    score: float


@dataclass
class SearchResult:
    query: str
    hits: list[Hit] = field(default_factory=list)
    unit: str | None = None
    units: list[str] = field(default_factory=list)  # todas as unidades citadas (comparações)
    unit_name: str | None = None
    corporate: bool = False
    institutional: bool = False
    confident: bool = False
    coverage: float = 0.0

    @property
    def ids(self) -> list[str]:
        return [hit.entry.id for hit in self.hits]


class Searcher:
    def __init__(self, entries: list[Entry], aliases: dict) -> None:
        self._entries = entries
        self._stop = {normalize(w) for w in aliases.get("stopwords", [])}
        self._units = {
            key: {
                "name": data["name"],
                "aliases": [tokenize(alias, self._stop, use_stem=False) for alias in data["aliases"]],
            }
            for key, data in aliases.get("units", {}).items()
        }
        self._institutional = [tokenize(t, self._stop) for t in aliases.get("institutional_triggers", [])]
        # frases de intenção comparadas no texto original (sem remover "minha", "sou"...): "minha empresa" != "empresa"
        self._corporate_phrases = [normalize(t).split() for t in aliases.get("corporate_triggers", [])]
        self._synonyms: dict[str, list[list[str]]] = {}
        self._reverse: dict[str, list[str]] = {}  # termo-valor -> chaves (sinônimo no sentido inverso)
        for key, values in aliases.get("synonyms", {}).items():
            key_token = stem(normalize(key))
            self._synonyms[key_token] = [tokenize(v, self._stop) for v in values]
            for phrase in self._synonyms[key_token]:
                if len(phrase) == 1:
                    self._reverse.setdefault(phrase[0], []).append(key_token)
        self._demote = {
            entry_id: [tokenize(t, self._stop) for t in terms]
            for entry_id, terms in aliases.get("demote_unless", {}).items()
        }
        self._build_index()

    # ---------- índice ----------
    def _build_index(self) -> None:
        self._tf: list[dict[str, float]] = []
        self._len: list[float] = []
        self._kw_phrases: list[list[list[str]]] = []
        self._question_sets: list[list[set[str]]] = []
        df: dict[str, int] = {}
        for entry in self._entries:
            tf: dict[str, float] = {}

            def add(text: str, weight: float) -> None:
                for token in tokenize(text, self._stop):
                    tf[token] = tf.get(token, 0.0) + weight

            add(entry.title, FIELD_WEIGHTS["title"])
            for keyword in entry.keywords:
                add(keyword, FIELD_WEIGHTS["keywords"])
            for question in entry.questions:
                add(question, FIELD_WEIGHTS["questions"])
            add(entry.content, FIELD_WEIGHTS["content"])
            self._tf.append(tf)
            self._len.append(sum(tf.values()))
            self._kw_phrases.append([t for t in (tokenize(k, self._stop) for k in entry.keywords) if len(t) >= 2])
            self._question_sets.append([set(tokenize(q, self._stop)) for q in entry.questions])
            for token in tf:
                df[token] = df.get(token, 0) + 1
        n = max(len(self._entries), 1)
        self._avg = (sum(self._len) / n) if self._len else 1.0
        self._idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}

    # ---------- detecção ----------
    def detect_units(self, query: str) -> list[str]:
        """Unidades citadas na pergunta, na ordem em que aparecem (aliases mais longos vencem os contidos neles)."""
        tokens = tokenize(query, self._stop, use_stem=False)
        found: list[tuple[int, int, str]] = []  # (posição, tamanho do alias, unidade)
        for key, data in self._units.items():
            best: tuple[int, int] | None = None
            for alias in data["aliases"]:
                if not alias or len(alias) > len(tokens):
                    continue
                for i in range(len(tokens) - len(alias) + 1):
                    if tokens[i:i + len(alias)] == alias and (best is None or len(alias) > best[1]):
                        best = (i, len(alias))
            if best:
                found.append((best[0], best[1], key))
        # um alias contido em outro mais longo da mesma região não conta como outra unidade
        kept = [f for f in found if not any(o is not f and o[0] <= f[0] and f[0] + f[1] <= o[0] + o[1] and o[1] > f[1] for o in found)]
        return [key for _, _, key in sorted(kept)]

    def detect_unit(self, query: str) -> str | None:
        units = self.detect_units(query)
        return units[0] if units else None

    def unit_name(self, key: str | None) -> str | None:
        return self._units[key]["name"] if key in self._units else None

    def is_corporate(self, query: str) -> bool:
        if CORPORATE_TOKENS & set(tokenize(query, self._stop)):
            return True
        raw = normalize(query).split()
        return any(contains_sequence(raw, phrase) for phrase in self._corporate_phrases)

    def _corporate_intent(self, query: str) -> bool:
        """Visitante que se apresenta como empresa/organização (ou pergunta sobre o Senac e empresas)."""
        raw = normalize(query).split()
        if any(contains_sequence(raw, phrase) for phrase in self._corporate_phrases):
            return True
        tokens = set(tokenize(query, self._stop))
        return bool(CORPORATE_TOKENS & tokens) and "senac" in tokens

    def is_institutional(self, query: str, unit: str | None, corporate: bool) -> bool:
        if unit or corporate:
            return True
        tokens = tokenize(query, self._stop)
        return any(contains_sequence(tokens, trigger) for trigger in self._institutional)

    # ---------- consulta ----------
    def _expand(self, tokens: list[str]) -> dict[str, float]:
        weights: dict[str, float] = {}
        for token in tokens:
            weights[token] = max(weights.get(token, 0.0), 1.0)
        for token in tokens:
            for phrase in self._synonyms.get(token, []):
                for sub in phrase:
                    weights[sub] = max(weights.get(sub, 0.0), 0.5)
        for key, phrases in self._synonyms.items():  # a pergunta usa uma expressão sinônima da chave
            for phrase in phrases:
                if len(phrase) >= 1 and contains_sequence(tokens, phrase):
                    weights[key] = max(weights.get(key, 0.0), 0.8)
        return weights

    def search(self, query: str, limit: int = 3) -> SearchResult:
        units = self.detect_units(query)
        unit = units[0] if units else None
        corporate = self.is_corporate(query)
        result = SearchResult(query=query, unit=unit, units=units, unit_name=self.unit_name(unit), corporate=corporate)
        result.institutional = self.is_institutional(query, unit, corporate)
        tokens = tokenize(query, self._stop)
        if not tokens:
            return result
        weights = self._expand(tokens)
        token_set = set(tokens)
        scored: list[Hit] = []
        for index, entry in enumerate(self._entries):
            if units and entry.unit not in (None, *units):
                continue  # nunca atribuir informação de uma unidade a outra
            tf = self._tf[index]
            norm = 1 - B + B * (self._len[index] / self._avg)
            score = 0.0
            for term, weight in weights.items():
                freq = tf.get(term)
                if freq:
                    score += weight * self._idf.get(term, 0.0) * (freq * (K1 + 1)) / (freq + K1 * norm)
            if score <= 0:
                continue
            bonus = 0.0
            for phrase in self._kw_phrases[index]:
                if contains_sequence(tokens, phrase):
                    bonus += 1.5
            score += min(bonus, 4.5)
            for qset in self._question_sets[index]:
                if qset and token_set:
                    overlap = len(qset & token_set) / len(qset | token_set)
                    if overlap >= 0.99:
                        score += 6.0
                    elif overlap >= 0.7:
                        score += 3.0
            if entry.unit is not None and entry.unit in units:
                score *= 1.5
            demote = self._demote.get(entry.id)
            if demote and not any(contains_sequence(tokens, term) for term in demote):
                score *= 0.35  # entrada de nicho: só lidera quando a pergunta cita o seu assunto
            scored.append(Hit(entry, score))
        scored.sort(key=lambda hit: hit.score, reverse=True)
        result.hits = scored[:limit]
        if corporate and not any(h.entry.category == "empresas" for h in result.hits):
            extra = next((h for h in scored if h.entry.category == "empresas"), None)
            if extra is not None:
                result.hits = result.hits[: limit - 1] + [extra] if len(result.hits) >= limit else result.hits + [extra]
        if len(units) >= 2:
            self._compare_units(result, scored, units, limit)
        if result.hits:
            result.coverage = self._coverage(tokens, result.hits[0].entry)
        # Pergunta geral (sem assunto institucional): só vale a base se ela cobrir quase tudo o que foi perguntado.
        needed = MIN_COVERAGE if (result.institutional or units) else MIN_COVERAGE_GENERAL
        result.confident = bool(result.hits) and result.hits[0].score >= MIN_SCORE and result.coverage >= needed
        if len(units) >= 2:
            result.confident = sum(1 for u in units if any(h.entry.unit == u for h in result.hits)) >= 2
        if not result.confident and self._corporate_intent(query):
            self._force_empresas(result, scored, limit)
        return result

    def _compare_units(self, result: SearchResult, scored: list[Hit], units: list[str], limit: int) -> None:
        """Comparação entre unidades: a melhor entrada de CADA unidade citada, lado a lado e rotuladas."""
        chosen: list[Hit] = []
        for unit in units:
            best = next((h for h in scored if h.entry.unit == unit), None)
            if best is not None:
                chosen.append(best)
        extras = [h for h in scored if h not in chosen and h.entry.unit is None]
        result.hits = (chosen + extras)[: max(limit, len(chosen))]

    def _force_empresas(self, result: SearchResult, scored: list[Hit], limit: int) -> None:
        """Quem fala como empresa deve conhecer o Senac Empresas, mesmo que a pergunta use palavras que a base não tem."""
        empresas = [h for h in scored if h.entry.category == "empresas"][:limit]
        if not empresas:
            defaults = [e for e in self._entries if e.id in ("empresas-o-que-e", "empresas-solucoes")]
            empresas = [Hit(e, MIN_SCORE) for e in defaults]
        if empresas:
            result.hits = empresas
            result.coverage = MIN_COVERAGE
            result.confident = True

    def _coverage(self, tokens: list[str], entry: Entry) -> float:
        """Quanto da pergunta a entrada realmente cobre; termos que a base desconhece pesam bastante."""
        index = self._entries.index(entry)
        tf = self._tf[index]
        unknown = math.log(1 + (len(self._entries) + 0.5) / 0.5)
        total = matched = 0.0
        for token in set(tokens):
            weight = self._idf.get(token, unknown)
            total += weight
            synonyms = {sub for phrase in self._synonyms.get(token, []) for sub in phrase}
            synonyms |= set(self._reverse.get(token, []))
            if token in tf or any(sub in tf for sub in synonyms):
                matched += weight
        return matched / total if total else 0.0
