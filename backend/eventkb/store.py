"""Persistência do Gerenciador de Eventos: uma pasta por evento (isolamento), escrita atômica e histórico.

events/
  active.json                 evento ativo (no máximo um por instância)
  <id>/event.json             cadastro e estado
  <id>/sources.json           fontes (do operador e descobertas)
  <id>/knowledge.json         itens de conhecimento com status, origem e histórico
  <id>/history.json           pesquisas, atualizações e decisões do operador
  <id>/snapshots/<fonte>.json texto da última versão válida de cada fonte
Os documentos acima são gravados por um DocStorage (arquivos ou MySQL; ver storage.py).
JSON basta aqui: poucos eventos, poucos milhares de itens, leitura por evento. Um banco de dados só se justificaria com
múltiplas instalações escrevendo ao mesmo tempo.
"""
import logging
import re
import threading
import unicodedata
from dataclasses import fields
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from backend.eventkb.storage import DocStorage, FileStorage, StorageError
from backend.eventkb.models import EVENT_STATES, ITEM_STATUSES, CATEGORIES, Event, EventItem, EventSource

logger = logging.getLogger("senac_bot.eventkb.store")

MAX_HISTORY = 500
REQUIRED = ("name", "area", "description", "start_date", "end_date")
LIST_FIELDS = {"social", "keywords", "reference_documents", "suggested_questions"}
EDITABLE = {f.name for f in fields(Event)} - {"id", "state", "created_at", "updated_at", "last_prepared_at", "last_updated_at", "last_scheduled_at"}


class EventStoreError(Exception):
    """Operação inválida (dados faltando, evento inexistente, estado incompatível). A mensagem é segura para o operador."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def slugify(text: str) -> str:
    plain = "".join(c for c in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "-", plain).strip("-")[:60] or "evento"


def _clean_list(value: Any) -> list[str]:
    if isinstance(value, str):
        value = re.split(r"[\n,;]+", value)
    return [str(v).strip() for v in (value or []) if str(v).strip()]


def _build(cls, data: dict[str, Any]):
    allowed = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in data.items() if k in allowed})


class EventStore:
    def __init__(self, root: Path, storage: DocStorage | None = None) -> None:
        self.root = Path(root)
        self._lock = threading.RLock()
        self.storage: DocStorage = storage or FileStorage(self.root)

    # ------------------------------------------------------------------ armazenamento
    def _read(self, key: str, default: Any) -> Any:
        try:
            value = self.storage.read(key)
        except StorageError as exc:
            raise EventStoreError(str(exc), 503) from None
        return default if value is None else value

    def _write(self, key: str, data: Any) -> None:
        try:
            self.storage.write(key, data)
        except StorageError as exc:
            raise EventStoreError(str(exc), 503) from None

    def _ids(self) -> list[str]:
        try:
            return self.storage.event_ids()
        except StorageError as exc:
            raise EventStoreError(str(exc), 503) from None

    # ------------------------------------------------------------------ caminhos
    def folder(self, event_id: str) -> Path:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,80}", event_id):
            raise EventStoreError("Identificador de evento inválido.")
        return self.root / event_id

    # ------------------------------------------------------------------ eventos
    def list_events(self, include_archived: bool = True) -> list[Event]:
        events: list[Event] = []
        with self._lock:
            for event_id in self._ids():
                raw = self._read(f"{event_id}/event.json", None)
                if isinstance(raw, dict) and raw.get("id") == event_id:
                    event = _build(Event, raw)
                    if include_archived or event.state != "archived":
                        events.append(event)
        return sorted(events, key=lambda e: (e.start_date, e.name))

    def get(self, event_id: str) -> Event:
        with self._lock:
            self.folder(event_id)
            raw = self._read(f"{event_id}/event.json", None)
        if not isinstance(raw, dict):
            raise EventStoreError("Evento não encontrado.", 404)
        return _build(Event, raw)

    def _validate(self, data: dict[str, Any]) -> dict[str, Any]:
        clean: dict[str, Any] = {}
        for key, value in data.items():
            if key not in EDITABLE:
                continue
            clean[key] = _clean_list(value) if key in LIST_FIELDS else (value.strip() if isinstance(value, str) else value)
        return clean

    @staticmethod
    def _check_required(values: dict[str, Any]) -> None:
        missing = [k for k in REQUIRED if not str(values.get(k, "")).strip()]
        if missing:
            raise EventStoreError("Campos obrigatórios ausentes: " + ", ".join(missing) + ".")
        try:
            start, end = date.fromisoformat(values["start_date"]), date.fromisoformat(values["end_date"])
        except ValueError:
            raise EventStoreError("As datas devem estar no formato AAAA-MM-DD.") from None
        if end < start:
            raise EventStoreError("A data de término não pode ser anterior à de início.")
        for key in ("website", "program_url"):
            if values.get(key) and not re.match(r"https?://[^\s]+$", str(values[key])):
                raise EventStoreError(f"O campo {key} deve ser um endereço http(s) válido.")

    def create(self, data: dict[str, Any]) -> Event:
        values = self._validate(data)
        self._check_required(values)
        with self._lock:
            base = slugify(f"{values['name']}")
            event_id, n = base, 2
            while self.storage.exists(f"{event_id}/event.json") or event_id in self._ids():
                event_id, n = f"{base}-{n}", n + 1
            stamp = now_iso()
            event = _build(Event, {**values, "id": event_id, "state": "draft", "created_at": stamp, "updated_at": stamp})
            self._save_event(event)
            self._write_sources(event_id, [])
            self._write_items(event_id, [])
            self.add_history(event_id, "cadastro", "Evento cadastrado.")
        return event

    def update(self, event_id: str, changes: dict[str, Any]) -> Event:
        with self._lock:
            event = self.get(event_id)
            if event.state == "archived":
                raise EventStoreError("Evento arquivado: reative-o antes de editar.", 409)
            merged = {**event.to_dict(), **self._validate(changes)}
            self._check_required(merged)
            merged["updated_at"] = now_iso()
            updated = _build(Event, merged)
            self._save_event(updated)
            self.add_history(event_id, "edicao", "Cadastro do evento editado.")
        return updated

    def set_state(self, event_id: str, state: str, **extra: Any) -> Event:
        if state not in EVENT_STATES:
            raise EventStoreError("Estado de evento inválido.")
        with self._lock:
            event = self.get(event_id)
            data = {**event.to_dict(), "state": state, "updated_at": now_iso(), **extra}
            updated = _build(Event, data)
            self._save_event(updated)
        return updated

    def _save_event(self, event: Event) -> None:
        self.folder(event.id)
        self._write(f"{event.id}/event.json", event.to_dict())

    # ------------------------------------------------------------------ evento ativo
    def active_id(self) -> str | None:
        with self._lock:
            raw = self._read("active.json", {})
        event_id = raw.get("event_id") if isinstance(raw, dict) else None
        return event_id if isinstance(event_id, str) and self.storage.exists(f"{event_id}/event.json") else None

    def set_active_id(self, event_id: str | None) -> None:
        with self._lock:
            self._write("active.json", {"event_id": event_id, "changed_at": now_iso()})

    # ------------------------------------------------------------------ fontes
    def sources(self, event_id: str) -> list[EventSource]:
        with self._lock:
            self.folder(event_id)
            raw = self._read(f"{event_id}/sources.json", {"sources": []})
        return [_build(EventSource, s) for s in raw.get("sources", [])]

    def _write_sources(self, event_id: str, sources: list[EventSource]) -> None:
        from dataclasses import asdict
        self._write(f"{event_id}/sources.json", {"sources": [asdict(s) for s in sources]})

    def save_sources(self, event_id: str, sources: list[EventSource]) -> None:
        with self._lock:
            self._write_sources(event_id, sources)

    # ------------------------------------------------------------------ itens
    def items(self, event_id: str) -> list[EventItem]:
        with self._lock:
            self.folder(event_id)
            raw = self._read(f"{event_id}/knowledge.json", {"items": []})
        items = []
        for item in raw.get("items", []):
            built = _build(EventItem, item)
            if built.category in CATEGORIES and built.status in ITEM_STATUSES:
                items.append(built)
        return items

    def _write_items(self, event_id: str, items: list[EventItem]) -> None:
        self._write(f"{event_id}/knowledge.json", {"items": [i.to_dict() for i in items]})

    def save_items(self, event_id: str, items: list[EventItem]) -> None:
        with self._lock:
            ids = [i.id for i in items]
            if len(ids) != len(set(ids)):
                raise EventStoreError("Identificadores de item duplicados.", 500)
            self._write_items(event_id, items)

    def get_item(self, event_id: str, item_id: str) -> EventItem:
        item = next((i for i in self.items(event_id) if i.id == item_id), None)
        if item is None:
            raise EventStoreError("Informação não encontrada.", 404)
        return item

    # ------------------------------------------------------------------ histórico e snapshots
    def history(self, event_id: str) -> list[dict[str, Any]]:
        with self._lock:
            self.folder(event_id)
            raw = self._read(f"{event_id}/history.json", {"entries": []})
        return list(raw.get("entries", []))

    def add_history(self, event_id: str, kind: str, summary: str, details: dict[str, Any] | None = None) -> None:
        with self._lock:
            entries = self.history(event_id)
            entries.append({"at": now_iso(), "kind": kind, "summary": summary, "details": details or {}})
            self._write(f"{event_id}/history.json", {"entries": entries[-MAX_HISTORY:]})

    def snapshot(self, event_id: str, source_id: str) -> dict[str, Any] | None:
        self.folder(event_id)
        raw = self._read(f"{event_id}/snapshots/{source_id}.json", None)
        return raw if isinstance(raw, dict) else None

    def save_snapshot(self, event_id: str, source_id: str, data: dict[str, Any]) -> None:
        with self._lock:
            self._write(f"{event_id}/snapshots/{source_id}.json", data)


def _item_id_unique(origin: str, title: str, text: str, taken: set[str]) -> str:
    """Identificador estável para itens criados fora de uma fonte (cadastro, operador)."""
    import hashlib  # noqa: PLC0415
    base = "it-" + hashlib.sha1(f"{origin}|{title}|{text}".encode("utf-8")).hexdigest()[:10]
    item_id, n = base, 2
    while item_id in taken:
        item_id, n = f"{base}-{n}", n + 1
    return item_id
