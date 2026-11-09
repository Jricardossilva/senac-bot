"""Pesquisa, preparação e atualização do conhecimento de um evento.

Princípios:
 - só se guarda TEXTO LITERAL das fontes (nada é inventado nem resumido por IA); sem resultado, não há item;
 - página existente não é informação confirmada: o item só fica CONFIRMADO quando vem de fonte oficial (declarada pelo
   operador, ou link do mesmo site oficial), a página é do evento e a regra de confiança permite; senão aguarda validação;
 - o que o operador aprovou ou editou nunca é sobrescrito: uma versão nova vira proposta ("Atualizações") aguardando decisão;
 - conteúdo da internet é DADO: blocos com cara de instrução (tentativa de manipular o robô) são rejeitados;
 - falha de uma fonte preserva a última versão válida; nada é marcado desatualizado por causa de uma falha de rede.
"""
import hashlib
import ipaddress
import logging
import re
import socket
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from difflib import SequenceMatcher
from urllib.parse import urldefrag, urljoin, urlparse

from backend.eventkb.extract import Block, ParsedPage, content_fingerprint, extract_facts, fold, make_block, parse_page
from backend.eventkb.models import Event, EventItem, EventSource
from backend.eventkb.store import EventStore, EventStoreError, now_iso
from backend.knowledge.fetch import PoliteFetcher
from backend.knowledge.text import normalize
from backend.policy import check_message

logger = logging.getLogger("senac_bot.eventkb.research")

MAX_PAGES_PER_RUN = 20
MAX_BYTES = 3_000_000
SNAPSHOT_TEXT_LIMIT = 200_000
MATCH_RATIO = 0.75
FOLLOW_LINKS = re.compile(r"program|agenda|cronograma|palestr|oficina|atividade|competi|expositor|visit|inscri|faq|duvida|noticia|local|sobre|como-chegar|sobre-o|ingresso", re.I)
OFFICIAL, CANDIDATE, THIRD = "official", "candidate", "third_party"
EVENT_DATE_TEXT = re.compile(r"acontece|ocorre|ocorrera|realiza|sera realizad|data do evento|periodo|edicao|de \d{1,2} a \d{1,2}|\d{1,2} a \d{1,2} de")

DiscoveryFn = Callable[[Event], list[str]]
Progress = Callable[[str, int, int], None]


@dataclass
class ResearchReport:
    mode: str
    sources_checked: int = 0
    sources_failed: list[str] = field(default_factory=list)
    new_items: int = 0
    changed_items: int = 0
    stale_items: int = 0
    divergent_items: int = 0
    rejected_items: int = 0
    proposals: int = 0
    messages: list[str] = field(default_factory=list)

    def summary(self) -> str:
        parts = [f"{self.sources_checked} fonte(s) consultada(s)", f"{self.new_items} nova(s)", f"{self.changed_items} alterada(s)",
                 f"{self.stale_items} desatualizada(s)", f"{self.divergent_items} divergente(s)", f"{self.proposals} proposta(s) de atualização"]
        if self.sources_failed:
            parts.append(f"{len(self.sources_failed)} fonte(s) com falha")
        return ", ".join(parts) + "."


# ------------------------------------------------------------------------------------------------ segurança de endereços
def is_public_url(url: str, resolver: Callable[[str], list[str]] | None = None) -> bool:
    """Só http(s) para a internet pública: recusa localhost, redes privadas e endereços internos (evita SSRF)."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in ("http", "https") or not host or parsed.username or parsed.password:
        return False
    if host == "localhost" or host.endswith((".local", ".localhost", ".internal", ".lan", ".home")):
        return False
    addresses = [host]
    try:
        ipaddress.ip_address(host)
    except ValueError:
        addresses = resolver(host) if resolver else []
        if resolver and not addresses:
            return False  # o nome não resolve: não acessar
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            return False
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            return False
    return True


def system_resolver(host: str) -> list[str]:
    try:
        return sorted({info[4][0] for info in socket.getaddrinfo(host, None)})
    except OSError:
        return []


def _host(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _source_id(url: str) -> str:
    return "src-" + hashlib.sha1(urldefrag(url)[0].encode("utf-8")).hexdigest()[:10]


def _item_id(source_id: str, heading: str, text: str, taken: set[str]) -> str:
    base = "it-" + hashlib.sha1(f"{source_id}|{normalize(heading)}|{normalize(text)[:80]}".encode("utf-8")).hexdigest()[:10]
    item_id, n = base, 2
    while item_id in taken:
        item_id, n = f"{base}-{n}", n + 1
    return item_id


def _identity_ok(event: Event, page: ParsedPage) -> bool:
    """A página fala do evento? Pelo menos metade das palavras distintas do nome aparece no texto."""
    words = {w for w in normalize(event.name).split() if len(w) > 2}
    if not words:
        return True
    text = normalize(page.title + " " + page.text)
    return sum(1 for w in words if w in text) / len(words) >= 0.5


def _date_pt(value: str) -> str:
    months = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]
    try:
        d = date.fromisoformat(value)
    except ValueError:
        return value
    return f"{d.day} de {months[d.month - 1]} de {d.year}"


class EventResearcher:
    def __init__(
        self,
        store: EventStore,
        fetcher_factory: Callable[[], PoliteFetcher],
        discovery: DiscoveryFn | None = None,
        resolver: Callable[[str], list[str]] | None = system_resolver,
        max_pages: int = MAX_PAGES_PER_RUN,
        today: Callable[[], date] = date.today,
    ) -> None:
        self._store = store
        self._fetcher_factory = fetcher_factory
        self._discovery = discovery
        self._resolver = resolver
        self._max_pages = max_pages
        self._today = today

    # ------------------------------------------------------------------ entrada
    def prepare(self, event_id: str, progress: Progress | None = None) -> ResearchReport:
        return self._run(event_id, "preparo", progress)

    def update(self, event_id: str, progress: Progress | None = None) -> ResearchReport:
        return self._run(event_id, "atualizacao", progress)

    # ------------------------------------------------------------------ execução
    def _run(self, event_id: str, mode: str, progress: Progress | None) -> ResearchReport:
        event = self._store.get(event_id)
        if event.state == "archived":
            raise EventStoreError("Evento arquivado: reative-o antes de pesquisar.", 409)
        report = ResearchReport(mode=mode)
        step = progress or (lambda *_: None)
        sources = self._sync_sources(event)
        items = self._store.items(event_id)

        if not any(s.trust == OFFICIAL for s in sources):
            step("Procurando o site oficial", 0, 1)
            found = self._discover(event, sources, report)
            sources += found
        if not sources:
            report.messages.append("Nenhuma fonte disponível: informe o site oficial, a página de programação ou outra fonte pública.")

        items = self._sync_registry(event, items)
        fetcher = self._fetcher_factory()
        queue = [s for s in sources]
        visited: set[str] = set()
        pages = 0
        while queue and pages < self._max_pages:
            source = queue.pop(0)
            if source.id in visited:
                continue
            visited.add(source.id)
            step(f"Consultando {source.url}", pages, min(len(queue) + pages + 1, self._max_pages))
            parsed = self._consult(event, source, fetcher, report)
            pages += 1
            if parsed is None:
                continue
            report.sources_checked += 1
            if source.trust == OFFICIAL:
                for extra in self._follow_links(event, source, parsed, sources):
                    sources.append(extra)
                    queue.append(extra)
            items = self._merge(event, source, parsed, items, report)

        self._mark_divergences(event, items, report)
        for item in items:
            if item.status == "rejected":
                report.rejected_items += 1
        self._store.save_items(event_id, items)
        self._store.save_sources(event_id, sources)
        stamp = now_iso()
        extra = {"last_prepared_at": stamp} if mode == "preparo" else {"last_updated_at": stamp}
        state = event.state
        if state == "draft" and any(i.status != "rejected" for i in items):
            state = "prepared"
        self._store.set_state(event_id, state, **extra)
        self._store.add_history(event_id, "pesquisa" if mode == "preparo" else "atualizacao", report.summary(),
                                {"fontes": [s.url for s in sources], "falhas": report.sources_failed, "mensagens": report.messages})
        return report

    # ------------------------------------------------------------------ fontes
    def _sync_sources(self, event: Event) -> list[EventSource]:
        sources = self._store.sources(event.id)
        known = {s.url: s for s in sources}

        def ensure(url: str, kind: str) -> None:
            if url and url not in known:
                source = EventSource(id=_source_id(url), url=url, kind=kind, trust=OFFICIAL, origin="operator")
                known[url] = source
                sources.append(source)

        ensure(event.website, "site")
        ensure(event.program_url, "program")
        for url in event.social:
            ensure(url, "social")
        for url in event.reference_documents:
            ensure(url, "document")
        return sources

    def _discover(self, event: Event, sources: list[EventSource], report: ResearchReport) -> list[EventSource]:
        if self._discovery is None:
            report.messages.append("Sem site oficial informado e sem pesquisa automática disponível: informe o site ou outras fontes públicas.")
            return []
        try:
            urls = self._discovery(event)
        except Exception as error:  # noqa: BLE001 - a descoberta é opcional
            logger.warning("Descoberta de fontes falhou (%s).", type(error).__name__)
            report.messages.append("A pesquisa automática do site oficial não está disponível agora.")
            return []
        known = {s.url for s in sources}
        found = []
        for url in urls[:5]:
            if url not in known and is_public_url(url, self._resolver):
                found.append(EventSource(id=_source_id(url), url=url, kind="site", trust=CANDIDATE, origin="discovered",
                                         note="Encontrada pela pesquisa automática; confirme se é o site oficial."))
        if found:
            report.messages.append(f"{len(found)} fonte(s) candidata(s) encontrada(s): o conteúdo só será usado depois que você confirmar a fonte ou aprovar os itens.")
        else:
            report.messages.append("Não encontrei um site oficial: informe o site ou outras fontes públicas.")
        return found

    def _follow_links(self, event: Event, source: EventSource, page: ParsedPage, sources: list[EventSource]) -> list[EventSource]:
        """Links do próprio site oficial que levam a programação, palestrantes, visitação etc. (mesmo domínio)."""
        known = {s.url for s in sources}
        extra: list[EventSource] = []
        for text, href in page.links:
            url = urldefrag(urljoin(source.url, href))[0]
            if url in known or _host(url) != _host(source.url) or not FOLLOW_LINKS.search(fold(text) + " " + url.lower()):
                continue
            if re.search(r"\.(pdf|jpe?g|png|gif|zip|docx?|xlsx?|mp4)$", url.lower()) or not is_public_url(url, self._resolver):
                continue
            known.add(url)
            extra.append(EventSource(id=_source_id(url), url=url, kind="program" if re.search("program|agenda|cronograma", url, re.I) else "site",
                                     trust=OFFICIAL, origin="discovered", note=f"Link do site oficial: {text[:60]}"))
        return extra

    # ------------------------------------------------------------------ consulta de uma fonte
    def _consult(self, event: Event, source: EventSource, fetcher: PoliteFetcher, report: ResearchReport) -> ParsedPage | None:
        source.last_checked = now_iso()
        if source.kind == "document" and source.url.lower().endswith(".pdf"):
            return self._fail(source, "documento PDF: informe o conteúdo manualmente ou use uma página HTML", report)
        response, problem = fetcher.fetch(source.url, lambda u: is_public_url(u, self._resolver), "endereço não permitido")
        if response is None:
            return self._fail(source, problem, report)
        if response.status_code != 200:
            return self._fail(source, f"HTTP {response.status_code}", report)
        if "html" not in response.headers.get("content-type", "text/html").lower():
            return self._fail(source, "conteúdo não é HTML", report)
        if len(response.content) > MAX_BYTES:
            return self._fail(source, "página grande demais", report)
        page = parse_page(response.text)
        if len(page.text) < 80:
            return self._fail(source, "página sem conteúdo legível (possivelmente carregada por JavaScript)", report)
        source.last_ok, source.error, source.failures, source.title = now_iso(), None, 0, page.title[:120]
        digest = content_fingerprint(page.text)
        unchanged = source.hash == digest
        source.hash = digest
        self._store.save_snapshot(event.id, source.id, {"id": source.id, "url": source.url, "fetched_at": now_iso(), "sha256": digest,
                                                          "title": page.title, "text": page.text[:SNAPSHOT_TEXT_LIMIT]})
        if unchanged and self._has_items_from(event.id, source.id):
            report.sources_checked += 1
            report.messages.append(f"Sem mudança em {source.url} (cache).")
            return None  # página igual à da última consulta: nada a reprocessar
        return page

    def _has_items_from(self, event_id: str, source_id: str) -> bool:
        return any(source_id in i.source_ids for i in self._store.items(event_id))

    @staticmethod
    def _fail(source: EventSource, reason: str, report: ResearchReport) -> None:
        source.error = reason
        source.failures += 1
        report.sources_failed.append(f"{source.url}: {reason}")
        return None

    # ------------------------------------------------------------------ cadastro como fonte (informado pelo operador)
    def _sync_registry(self, event: Event, items: list[EventItem]) -> list[EventItem]:
        stamp = now_iso()
        wanted: dict[str, tuple[str, str, str]] = {}
        period = f"de {_date_pt(event.start_date)} a {_date_pt(event.end_date)}" if event.start_date != event.end_date else f"em {_date_pt(event.start_date)}"
        wanted["about"] = ("about", event.name, f"{event.name} é um evento de {event.area}. {event.description}".strip())
        wanted["dates"] = ("dates", "Datas do evento", f"{event.name} acontece {period}.")
        where = ", ".join(p for p in (event.venue, f"{event.city}/{event.uf}" if event.city and event.uf else event.city or event.uf) if p)
        if where:
            wanted["location"] = ("location", "Local do evento", f"{event.name} acontece em {where}.")
        if event.organization:
            wanted["organization"] = ("organization", "Organização", f"A organização responsável pelo evento é {event.organization}.")
        if event.objective:
            wanted["objectives"] = ("objectives", "Objetivo do evento", event.objective)
        if event.audience:
            wanted["visitor_info"] = ("visitor_info", "Público esperado", f"O público esperado do evento é: {event.audience}.")
        by_registry = {i.key_facts.get("registry"): i for i in items if i.key_facts.get("registry")}
        for key, (category, title, content) in wanted.items():
            existing = by_registry.get(key)
            facts = extract_facts(content, int(event.start_date[:4]) if event.start_date[:4].isdigit() else None)
            facts["registry"] = key
            if existing is None:
                taken = {i.id for i in items}
                items.append(EventItem(id=_item_id("cadastro", key, content, taken), category=category, title=title, content=content,
                                       status="confirmed", approved_by="operator", found_at=stamp, updated_at=stamp,
                                       valid_until=event.end_date, key_facts=facts, note="Informado no cadastro do evento."))
            elif not existing.edited and existing.content != content:
                self._log(existing, "cadastro atualizado", existing.content, content)
                existing.content, existing.updated_at, existing.key_facts = content, stamp, facts
        for key, existing in by_registry.items():
            if key not in wanted and not existing.edited:
                existing.status, existing.note = "stale", "Campo removido do cadastro."
        return items

    # ------------------------------------------------------------------ mesclagem
    def _merge(self, event: Event, source: EventSource, page: ParsedPage, items: list[EventItem], report: ResearchReport) -> list[EventItem]:
        stamp = now_iso()
        year = int(event.start_date[:4]) if event.start_date[:4].isdigit() else None
        identity = _identity_ok(event, page)
        candidates = [(b.heading, b) for b in page.blocks]
        for node in page.structured:  # JSON-LD schema.org/Event: dados estruturados publicados pelo organizador
            candidates += [("Dados estruturados do evento", b) for b in self._structured_blocks(node)]
        if page.description:
            description = make_block("Descrição", page.description)
            description.category = "about"
            candidates.insert(0, ("Descrição", description))
        seen: set[str] = set()
        taken = {i.id for i in items}
        heading_count: dict[str, int] = {}
        for heading, _ in candidates:
            heading_count[normalize(heading)] = heading_count.get(normalize(heading), 0) + 1
        for heading, block in candidates:
            block.facts = extract_facts(block.text, year)
            existing = self._find(items, source.id, heading, block.text, seen, heading_count.get(normalize(heading), 0) == 1)
            if existing is not None and existing.status == "rejected":
                seen.add(existing.id)
                continue  # o operador já rejeitou esta informação: não ressuscitar
            if existing is None:
                item = self._new_item(event, source, heading, block, identity, taken)
                taken.add(item.id)
                items.append(item)
                seen.add(item.id)
                report.new_items += 1
                continue
            seen.add(existing.id)
            self._update_existing(event, source, existing, block, identity, items, taken, report)
        for item in items:  # informação desta fonte que sumiu da página: marcar como antiga (só se a consulta funcionou)
            if source.id in item.source_ids and item.category != "updates" and item.id not in seen and item.status not in ("rejected", "stale") and not item.edited and item.approved_by != "operator":
                item.status, item.updated_at = "stale", stamp
                item.note = "Não encontrada na última consulta da fonte."
                self._log(item, "desatualizada", item.content, "(não encontrada)")
                report.stale_items += 1
        return items

    @staticmethod
    def _structured_blocks(node: dict) -> list[Block]:
        out: list[Block] = []
        name, start, end = node.get("name"), node.get("startDate"), node.get("endDate")
        if name and start:
            text = f"{name}: início em {start}" + (f", término em {end}" if end else "") + "."
            block = make_block("Datas (dados estruturados)", text)
            block.category = "dates"
            out.append(block)
        location = node.get("location")
        if isinstance(location, dict) and (location.get("name") or location.get("address")):
            address = location.get("address")
            if isinstance(address, dict):
                address = ", ".join(str(address.get(k)) for k in ("streetAddress", "addressLocality", "addressRegion") if address.get(k))
            text = "Local: " + ", ".join(str(p) for p in (location.get("name"), address) if p) + "."
            block = make_block("Local (dados estruturados)", text)
            block.category = "location"
            out.append(block)
        if node.get("description"):
            out.append(make_block("Descrição (dados estruturados)", str(node["description"])))
        return out

    def _find(self, items: list[EventItem], source_id: str, heading: str, text: str, claimed: set[str], unique_heading: bool) -> EventItem | None:
        """Item já conhecido que corresponde ao bloco: texto igual, ou muito parecido, ou mesmo título único (texto alterado).
        Cada item é associado a no máximo um bloco por consulta (dois blocos sob o mesmo título não se confundem)."""
        norm_text, norm_head = normalize(text), normalize(heading)
        pool = [i for i in items if source_id in i.source_ids and not i.key_facts.get("registry") and i.category != "updates" and i.id not in claimed]
        for item in pool:
            if normalize(item.content) == norm_text:
                return item
        best, best_ratio = None, 0.0
        for item in pool:
            ratio = SequenceMatcher(None, normalize(item.content), norm_text).ratio()
            if ratio >= MATCH_RATIO and ratio > best_ratio:
                best, best_ratio = item, ratio
        if best is None and unique_heading and norm_head:
            same = [i for i in pool if normalize(i.key_facts.get("heading", "")) == norm_head]
            if len(same) == 1 and SequenceMatcher(None, normalize(same[0].content), norm_text).ratio() >= 0.35:
                best = same[0]
        return best

    def _status_for(self, event: Event, source: EventSource, identity: bool, suspicious: bool) -> tuple[str, str | None]:
        if suspicious:
            return "rejected", None
        if source.trust == OFFICIAL and identity and event.auto_approve_official:
            return "confirmed", "auto"
        if source.trust == OFFICIAL:
            return "pending", None
        return "found", None

    def _new_item(self, event: Event, source: EventSource, heading: str, block: Block, identity: bool, taken: set[str]) -> EventItem:
        stamp = now_iso()
        suspicious = check_message(block.text) is not None or check_message(heading) is not None
        status, approved = self._status_for(event, source, identity, suspicious)
        note = ""
        if suspicious:
            note = "Conteúdo rejeitado automaticamente: parece uma instrução ao robô, não informação do evento."
        elif not identity:
            note = "A página não menciona claramente o evento: confirme antes de usar."
        elif block.truncated:
            note = "Texto reduzido ao tamanho falável; o conteúdo completo está na fonte."
        facts = dict(block.facts)
        facts["heading"] = heading
        category = block.category
        item = EventItem(
            id=_item_id(source.id, heading, block.text, taken), category=category, title=(heading or " ".join(block.text.split()[:8]))[:120],
            content=block.text, source_ids=[source.id], status=status, approved_by=approved, found_at=stamp, updated_at=stamp,
            valid_until=event.end_date, key_facts=facts, note=note,
        )
        if block.cancelled and status != "rejected":
            item.note = (note + " Menciona cancelamento ou adiamento.").strip()
            item.status = "pending" if status == "confirmed" else status
            item.approved_by = None
        item.history.append({"at": stamp, "change": "encontrada", "to": block.text})
        return item

    def _update_existing(self, event, source, existing: EventItem, block: Block, identity: bool, items: list[EventItem], taken: set[str], report: ResearchReport) -> None:
        stamp = now_iso()
        if normalize(existing.content) == normalize(block.text):
            if existing.status == "stale" and not existing.edited:  # voltou a aparecer na fonte
                existing.status = "confirmed" if existing.approved_by else "pending"
                existing.note = "Voltou a aparecer na fonte."
            existing.updated_at = stamp
            return
        old = existing.content
        facts_before = {k: v for k, v in existing.key_facts.items() if k in ("dates", "times")}
        facts_after = {k: v for k, v in block.facts.items() if k in ("dates", "times")}
        protected = existing.edited or existing.approved_by == "operator"
        if block.cancelled:
            if not protected:
                existing.status, existing.note = "stale", "A fonte indica cancelamento, adiamento ou mudança."
            report.stale_items += 0 if protected else 1
            self._proposal(event, source, existing, block, items, taken, report, "Possível cancelamento ou adiamento")
            self._log(existing, "possivel cancelamento", old, block.text)
            return
        if protected:
            self._proposal(event, source, existing, block, items, taken, report, "Nova versão encontrada na fonte")
            return
        if source.trust != OFFICIAL or not identity:
            self._proposal(event, source, existing, block, items, taken, report, "Nova versão de fonte não oficial")
            return
        # fonte oficial, item não protegido: atualiza e registra o histórico
        existing.content, existing.updated_at = block.text, stamp
        existing.key_facts = {**block.facts, "heading": existing.key_facts.get("heading", "")}
        existing.category = block.category
        self._log(existing, "alterada", old, block.text)
        report.changed_items += 1
        if facts_before != facts_after and (facts_before or facts_after):
            summary = f"Houve uma mudança em \"{existing.title}\": agora, {block.text}"
            self._add_update_item(event, source, existing, summary, items, taken, status="confirmed", approved="auto", report=report)

    def _proposal(self, event, source, existing, block, items, taken, report, label) -> None:
        """Versão nova que NÃO substitui o aprovado: vira item de 'Atualizações' aguardando decisão do operador."""
        fp = content_fingerprint(block.text)
        if any(i.key_facts.get("replaces") == existing.id and i.key_facts.get("fp") == fp for i in items):
            return  # a mesma proposta já foi registrada (e talvez rejeitada)
        text = f"{label} para \"{existing.title}\": {block.text}"
        self._add_update_item(event, source, existing, text, items, taken, status="pending", approved=None, report=report, fp=fp, replacement=block.text)

    def _add_update_item(self, event, source, existing, text, items, taken, status, approved, report, fp=None, replacement=None) -> None:
        stamp = now_iso()
        facts = {"replaces": existing.id, "fp": fp or content_fingerprint(text)}
        if replacement is not None:
            facts["replacement"] = replacement
        item = EventItem(id=_item_id(source.id, "update", text, taken), category="updates", title=f"Atualização: {existing.title}"[:120],
                         content=" ".join(text.split()[: 90]), source_ids=[source.id], status=status, approved_by=approved,
                         found_at=stamp, updated_at=stamp, valid_until=event.end_date, key_facts=facts,
                         note="Proposta de atualização: aprove para substituir a informação anterior." if status == "pending" else "Mudança detectada na fonte oficial.")
        taken.add(item.id)
        items.append(item)
        report.proposals += 1 if status == "pending" else 0

    @staticmethod
    def _log(item: EventItem, change: str, before: str, after: str) -> None:
        item.history.append({"at": now_iso(), "change": change, "from": before, "to": after})
        item.history = item.history[-30:]

    # ------------------------------------------------------------------ divergências
    def _mark_divergences(self, event: Event, items: list[EventItem], report: ResearchReport) -> None:
        """Datas do evento que discordam do cadastro ou entre fontes: marcadas como divergentes (o operador decide)."""
        period = set(_period_dates(event))

        def full_dates(item: EventItem) -> set[str]:
            return {d for d in item.key_facts.get("dates", []) if not d.startswith("----")}

        def about_event_dates(item: EventItem) -> bool:
            return item.category == "dates" and bool(full_dates(item)) and bool(EVENT_DATE_TEXT.search(fold(item.content)))

        dated = [i for i in items if i.status in ("found", "pending", "confirmed") and not i.key_facts.get("registry") and about_event_dates(i)]
        for item in dated:
            dates = full_dates(item)
            against_registry = bool(period) and dates.isdisjoint(period)
            against_sources = any(set(o.source_ids) != set(item.source_ids) and full_dates(o).isdisjoint(dates) for o in dated if o is not item)
            if (against_registry or against_sources) and item.approved_by != "operator":
                item.status, item.approved_by = "divergent", None
                item.note = "As datas desta fonte divergem do cadastro ou de outra fonte: confira antes de aprovar."
                self._log(item, "divergente", "", item.content)
                report.divergent_items += 1


def _period_dates(event: Event) -> list[str]:
    start, end = event.period
    if start is None or end is None:
        return []
    return [(start + timedelta(days=n)).isoformat() for n in range((end - start).days + 1)]
