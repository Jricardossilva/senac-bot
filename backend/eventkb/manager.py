"""Gerenciador de Eventos: fachada usada pela API e pelo chat.

 - cadastro/edição/arquivamento; pesquisa e atualização em segundo plano (um trabalho por vez);
 - validação humana (aprovar, editar, rejeitar, adicionar);
 - ativação: no máximo um evento ativo por instância; desativar NUNCA apaga dados;
 - atualização programada com limites (intervalo mínimo entre pesquisas; páginas por pesquisa limitadas no pesquisador).
"""
import logging
import threading
from collections import Counter
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from typing import Any

from backend.eventkb.knowledge import EventKnowledge
from backend.eventkb.models import CATEGORIES, CATEGORY_LABELS, ITEM_STATUSES, MAX_ITEM_WORDS, STATE_LABELS, STATUS_LABELS, Event, EventItem, EventSource
from backend.eventkb.research import EventResearcher, ResearchReport, _source_id, is_public_url, system_resolver
from backend.eventkb.store import EventStore, EventStoreError, _item_id_unique, now_iso

logger = logging.getLogger("senac_bot.eventkb")

MIN_MANUAL_GAP_SECONDS = 30  # evita pesquisas repetidas em sequência sobre o mesmo evento
MIN_SCHEDULE_HOURS = 1


class EventManager:
    def __init__(
        self,
        store: EventStore,
        researcher: EventResearcher,
        aliases: dict | None = None,
        today: Callable[[], date] = date.today,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        run_in_thread: bool = True,
    ) -> None:
        self.store = store
        self.researcher = researcher
        self._aliases = aliases or {}
        self._today = today
        self._clock = clock
        self._threaded = run_in_thread
        self._lock = threading.RLock()
        self._job: dict[str, Any] = {"running": False}
        self._active_cache: tuple[str, EventKnowledge] | None = None
        self._version = 0  # muda a cada alteração de itens/estado: invalida o cache do evento ativo
        self._last_run: dict[str, datetime] = {}

    def _guard_not_researching(self, event_id: str) -> None:
        """A pesquisa grava a lista inteira de itens/fontes ao terminar: editar durante ela perderia a edição do operador."""
        with self._lock:
            if self._job.get("running") and self._job.get("event_id") == event_id:
                raise EventStoreError("Pesquisa em andamento neste evento: aguarde terminar para alterar informações ou fontes.", 409)

    # ------------------------------------------------------------------ consulta
    def summarize(self, event: Event) -> dict[str, Any]:
        items = self.store.items(event.id)
        counts = Counter(i.status for i in items)
        return {
            **event.to_dict(), "state_label": STATE_LABELS.get(event.state, event.state),
            "active": self.store.active_id() == event.id,
            "counts": {s: counts.get(s, 0) for s in ITEM_STATUSES},
            "confirmed": counts.get("confirmed", 0), "pending": counts.get("pending", 0) + counts.get("found", 0) + counts.get("divergent", 0),
            "items_total": len(items), "sources_total": len(self.store.sources(event.id)),
        }

    def list_events(self) -> list[dict[str, Any]]:
        return [self.summarize(e) for e in self.store.list_events()]

    def detail(self, event_id: str) -> dict[str, Any]:
        event = self.store.get(event_id)
        items = self.store.items(event_id)
        grouped: dict[str, list[dict[str, Any]]] = {}
        for item in items:
            grouped.setdefault(item.category, []).append({**item.to_dict(), "status_label": STATUS_LABELS.get(item.status, item.status)})
        return {
            "event": self.summarize(event),
            "sources": [s.__dict__ for s in self.store.sources(event_id)],
            "categories": [{"id": c, "label": CATEGORY_LABELS[c], "items": grouped.get(c, [])} for c in CATEGORIES if grouped.get(c)],
            "history": self.store.history(event_id)[-60:][::-1],
            "job": self.job_status(event_id),
        }

    # ------------------------------------------------------------------ cadastro
    def create(self, data: dict[str, Any]) -> dict[str, Any]:
        event = self.store.create(data)
        return self.summarize(event)

    def update(self, event_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        event = self.store.update(event_id, changes)
        if event.update_interval_hours and event.update_interval_hours < MIN_SCHEDULE_HOURS:
            event = self.store.update(event_id, {"update_interval_hours": MIN_SCHEDULE_HOURS})
        self._invalidate(event_id)
        return self.summarize(event)

    def archive(self, event_id: str) -> dict[str, Any]:
        if self.store.active_id() == event_id:
            self.deactivate()
        event = self.store.set_state(event_id, "archived")
        self.store.add_history(event_id, "arquivo", "Evento arquivado (os dados foram preservados).")
        return self.summarize(event)

    def unarchive(self, event_id: str) -> dict[str, Any]:
        event = self.store.get(event_id)
        if event.state != "archived":
            raise EventStoreError("O evento não está arquivado.", 409)
        has_items = bool(self.store.items(event_id))
        event = self.store.set_state(event_id, "prepared" if has_items else "draft")
        self.store.add_history(event_id, "arquivo", "Evento reativado do arquivo.")
        return self.summarize(event)

    # ------------------------------------------------------------------ fontes
    def add_source(self, event_id: str, url: str, kind: str = "other", trust: str = "official") -> dict[str, Any]:
        self.store.get(event_id)
        self._guard_not_researching(event_id)
        if not is_public_url(url, system_resolver):
            raise EventStoreError("Endereço não permitido: informe um site público (http ou https).")
        if trust not in ("official", "third_party", "candidate"):
            raise EventStoreError("Confiança da fonte inválida.")
        sources = self.store.sources(event_id)
        if any(s.url == url for s in sources):
            raise EventStoreError("Esta fonte já está cadastrada.", 409)
        source = EventSource(id=_source_id(url), url=url, kind=kind, trust=trust, origin="operator")
        sources.append(source)
        self.store.save_sources(event_id, sources)
        self.store.add_history(event_id, "fonte", f"Fonte adicionada ({trust}): {url}")
        return source.__dict__

    def set_source_trust(self, event_id: str, source_id: str, trust: str) -> dict[str, Any]:
        """Promove uma fonte candidata a oficial (ou rebaixa). Os itens já encontrados continuam aguardando validação."""
        if trust not in ("official", "third_party", "candidate"):
            raise EventStoreError("Confiança da fonte inválida.")
        self._guard_not_researching(event_id)
        sources = self.store.sources(event_id)
        source = next((s for s in sources if s.id == source_id), None)
        if source is None:
            raise EventStoreError("Fonte não encontrada.", 404)
        source.trust = trust
        self.store.save_sources(event_id, sources)
        self.store.add_history(event_id, "fonte", f"Fonte marcada como {trust}: {source.url}")
        return source.__dict__

    def remove_source(self, event_id: str, source_id: str) -> None:
        self._guard_not_researching(event_id)
        sources = self.store.sources(event_id)
        remaining = [s for s in sources if s.id != source_id]
        if len(remaining) == len(sources):
            raise EventStoreError("Fonte não encontrada.", 404)
        self.store.save_sources(event_id, remaining)
        self.store.add_history(event_id, "fonte", f"Fonte removida: {source_id}")

    # ------------------------------------------------------------------ validação humana
    def _decide(self, event_id: str, item_id: str, change) -> dict[str, Any]:
        with self._lock:
            self._guard_not_researching(event_id)
            items = self.store.items(event_id)
            item = next((i for i in items if i.id == item_id), None)
            if item is None:
                raise EventStoreError("Informação não encontrada.", 404)
            before = item.status
            change(item, items)
            item.updated_at = now_iso()
            self.store.save_items(event_id, items)
            self.store.add_history(event_id, "validacao", f"{item.title[:60]}: {before} → {item.status}", {"item": item.id})
            self._invalidate(event_id)
            return item.to_dict()

    def approve(self, event_id: str, item_id: str) -> dict[str, Any]:
        def change(item: EventItem, items: list[EventItem]) -> None:
            if item.category == "updates" and item.key_facts.get("replaces") and item.key_facts.get("replacement"):
                target = next((i for i in items if i.id == item.key_facts["replaces"]), None)
                if target is not None:  # aplica a proposta aprovada sobre o item original, preservando o histórico
                    target.history.append({"at": now_iso(), "change": "atualizacao aprovada", "from": target.content, "to": item.key_facts["replacement"]})
                    target.content, target.status, target.approved_by = item.key_facts["replacement"], "confirmed", "operator"
                    target.note = "Atualizado por proposta aprovada pelo operador."
                    target.updated_at = now_iso()
                item.status, item.approved_by, item.note = "confirmed", "operator", "Proposta aprovada e aplicada."
                item.key_facts = {k: v for k, v in item.key_facts.items() if k != "replacement"}
                item.content = f"Houve uma mudança em \"{target.title if target else item.title}\": agora, {target.content if target else ''}".strip()
                return
            item.status, item.approved_by = "confirmed", "operator"
            item.note = (item.note + " Aprovada pelo operador.").strip()
        return self._decide(event_id, item_id, change)

    def reject(self, event_id: str, item_id: str, reason: str = "") -> dict[str, Any]:
        def change(item: EventItem, items: list[EventItem]) -> None:
            item.status, item.approved_by = "rejected", None
            item.note = f"Rejeitada pelo operador. {reason}".strip()
        return self._decide(event_id, item_id, change)

    def edit_item(self, event_id: str, item_id: str, content: str | None = None, title: str | None = None, category: str | None = None) -> dict[str, Any]:
        def change(item: EventItem, items: list[EventItem]) -> None:
            if content is not None:
                text = " ".join(content.split())
                if not text or len(text.split()) > MAX_ITEM_WORDS:
                    raise EventStoreError(f"O texto deve ter de 1 a {MAX_ITEM_WORDS} palavras (será falado em voz alta).")
                from backend.policy import check_message  # noqa: PLC0415
                if check_message(text) is not None:
                    raise EventStoreError("O texto parece uma instrução ao robô ou traz informação sigilosa: reescreva como informação do evento.")
                item.history.append({"at": now_iso(), "change": "editada pelo operador", "from": item.content, "to": text})
                item.content, item.edited = text, True
            if title is not None:
                item.title = title.strip()[:120] or item.title
            if category is not None:
                if category not in CATEGORIES:
                    raise EventStoreError("Categoria inválida.")
                item.category = category
            item.status, item.approved_by = "confirmed", "operator"
        return self._decide(event_id, item_id, change)

    def add_item(self, event_id: str, category: str, title: str, content: str) -> dict[str, Any]:
        """Informação digitada pelo operador (confirmada por ele)."""
        event = self.store.get(event_id)
        text = " ".join(content.split())
        if category not in CATEGORIES or not title.strip() or not text or len(text.split()) > MAX_ITEM_WORDS:
            raise EventStoreError(f"Informe categoria, título e um texto de até {MAX_ITEM_WORDS} palavras.")
        from backend.policy import check_message  # noqa: PLC0415
        if check_message(text) is not None:
            raise EventStoreError("O texto parece uma instrução ao robô ou traz informação sigilosa: reescreva como informação do evento.")
        with self._lock:
            self._guard_not_researching(event_id)
            items = self.store.items(event_id)
            stamp = now_iso()
            item = EventItem(id=_item_id_unique("operador", title, text, {i.id for i in items}), category=category, title=title.strip()[:120], content=text,
                             status="confirmed", approved_by="operator", found_at=stamp, updated_at=stamp, valid_until=event.end_date,
                             note="Digitada pelo operador.", edited=True, history=[{"at": stamp, "change": "adicionada pelo operador", "to": text}])
            items.append(item)
            self.store.save_items(event_id, items)
            self.store.add_history(event_id, "validacao", f"Informação adicionada: {item.title[:60]}")
            self._invalidate(event_id)
            return item.to_dict()

    def approve_all_pending(self, event_id: str, statuses: tuple[str, ...] = ("pending",)) -> int:
        """Aprovação em lote, só de itens aguardando validação (nunca divergentes, rejeitados ou encontrados em fonte candidata)."""
        with self._lock:
            self._guard_not_researching(event_id)
            items = self.store.items(event_id)
            count = 0
            for item in items:
                if item.status in statuses and item.category != "updates":
                    item.status, item.approved_by, item.updated_at = "confirmed", "operator", now_iso()
                    count += 1
            self.store.save_items(event_id, items)
            self.store.add_history(event_id, "validacao", f"{count} informação(ões) aprovada(s) em lote.")
            self._invalidate(event_id)
            return count

    # ------------------------------------------------------------------ pesquisa em segundo plano
    def job_status(self, event_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            job = dict(self._job)
        if event_id and job.get("event_id") not in (None, event_id):
            return {"running": False}
        return job

    def start_research(self, event_id: str, mode: str = "prepare") -> dict[str, Any]:
        event = self.store.get(event_id)
        if event.state == "archived":
            raise EventStoreError("Evento arquivado: reative-o antes de pesquisar.", 409)
        with self._lock:
            if self._job.get("running"):
                raise EventStoreError("Já existe uma pesquisa em andamento. Aguarde terminar.", 409)
            last = self._last_run.get(event_id)
            now = self._clock()
            if last is not None and (now - last).total_seconds() < MIN_MANUAL_GAP_SECONDS:
                raise EventStoreError("Pesquisa recente: aguarde alguns instantes antes de pesquisar de novo.", 429)
            self._last_run[event_id] = now
            self._job = {"running": True, "event_id": event_id, "mode": mode, "step": "Iniciando", "done": 0, "total": 0, "started_at": now_iso()}
        if self._threaded:
            threading.Thread(target=self._run_job, args=(event_id, mode), daemon=True, name=f"event-research-{event_id}").start()
        else:
            self._run_job(event_id, mode)
        return self.job_status(event_id)

    def _run_job(self, event_id: str, mode: str) -> None:
        def progress(step: str, done: int, total: int) -> None:
            with self._lock:
                self._job.update({"step": step, "done": done, "total": total})
        report: ResearchReport | None = None
        error: str | None = None
        try:
            report = self.researcher.prepare(event_id, progress) if mode == "prepare" else self.researcher.update(event_id, progress)
        except EventStoreError as exc:
            error = exc.message
        except Exception:  # noqa: BLE001 - uma falha de pesquisa nunca derruba a aplicação
            logger.exception("Falha inesperada na pesquisa do evento %s.", event_id)
            error = "A pesquisa falhou por um erro inesperado. Veja os registros do servidor."
            try:
                self.store.add_history(event_id, "erro", error)
            except EventStoreError:
                pass
        finally:
            self._invalidate(event_id)
            with self._lock:
                self._job = {"running": False, "event_id": event_id, "mode": mode, "finished_at": now_iso(), "error": error,
                             "summary": report.summary() if report else None, "messages": report.messages if report else [],
                             "failed": report.sources_failed if report else []}

    # ------------------------------------------------------------------ ativação
    def activate(self, event_id: str) -> dict[str, Any]:
        with self._lock:
            event = self.store.get(event_id)
            if event.state == "archived":
                raise EventStoreError("Evento arquivado: reative-o antes de ativar.", 409)
            if not any(i.status == "confirmed" for i in self.store.items(event_id)):
                raise EventStoreError("Não há informações confirmadas: use PESQUISAR E PREPARAR EVENTO e valide o conteúdo antes de ativar.", 409)
            current = self.store.active_id()
            if current and current != event_id:
                self.deactivate()
            event = self.store.set_state(event_id, "active")
            self.store.set_active_id(event_id)
            self.store.add_history(event_id, "ativacao", "Evento ativado.")
            self._invalidate(event_id)
            return self.summarize(event)

    def deactivate(self) -> dict[str, Any] | None:
        with self._lock:
            current = self.store.active_id()
            if current is None:
                return None
            event = self.store.set_state(current, "inactive")
            self.store.set_active_id(None)
            self.store.add_history(current, "ativacao", "Evento desativado (dados preservados).")
            self._invalidate(current)
            return self.summarize(event)

    # ------------------------------------------------------------------ evento ativo (usado pelo chat)
    def _invalidate(self, event_id: str | None = None) -> None:
        with self._lock:
            self._version += 1
            self._active_cache = None

    def active(self) -> EventKnowledge | None:
        """Conhecimento do evento ativo (cache até qualquer alteração); None = experiência institucional genérica."""
        with self._lock:
            event_id = self.store.active_id()
            if event_id is None:
                self._active_cache = None
                return None
            if self._active_cache and self._active_cache[0] == event_id:
                return self._active_cache[1]
            try:
                event = self.store.get(event_id)
            except EventStoreError:
                return None
            sources = {s.id: s for s in self.store.sources(event_id)}
            knowledge = EventKnowledge(event, self.store.items(event_id), sources, self._aliases, self._today())
            self._active_cache = (event_id, knowledge)
            return knowledge

    def public_info(self) -> dict[str, Any]:
        """Só o que o visitante pode ver do evento ativo: nome, tema, período, boas-vindas e sugestões."""
        knowledge = self.active()
        if knowledge is None:
            return {"active": False}
        event = knowledge.event
        return {"active": True, "name": event.name, "area": event.area, "start_date": event.start_date, "end_date": event.end_date,
                "welcome": knowledge.welcome(), "suggested_questions": knowledge.suggested_questions(), "simulation": event.simulation}

    # ------------------------------------------------------------------ atualização programada
    def run_due_updates(self) -> str | None:
        """Chamada periódica: atualiza o evento cuja pesquisa programada venceu. Uma pesquisa por vez, com intervalo mínimo."""
        now = self._clock()
        for event in self.store.list_events(include_archived=False):
            if event.update_interval_hours < MIN_SCHEDULE_HOURS or event.state not in ("prepared", "active"):
                continue
            last_text = event.last_scheduled_at or event.last_updated_at or event.last_prepared_at
            last = datetime.fromisoformat(last_text) if last_text else None
            if last is not None and now - last < timedelta(hours=event.update_interval_hours):
                continue
            try:
                self.store.set_state(event.id, event.state, last_scheduled_at=now.isoformat(timespec="seconds"))
                self.start_research(event.id, "update")
                return event.id
            except EventStoreError:
                continue
        return None
