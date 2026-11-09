"""Gerenciador de Eventos: primeiro evento, proteção de endereços, privacidade e isolamento no código."""
import ast
from pathlib import Path

import pytest

from backend.eventkb.research import is_public_url
from backend.eventkb.seed import FIRST_EVENT, ensure_first_event
from tests.eventkb_helpers import FakeWeb, make_manager
from tests.kb_helpers import real_kb

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("url", [
    "http://localhost/x", "http://127.0.0.1:8000/", "http://10.0.0.1/", "http://192.168.0.5/", "http://172.16.0.1/", "http://169.254.169.254/latest",
    "http://[::1]/", "file:///etc/passwd", "ftp://exemplo.org/", "javascript:alert(1)", "http://usuario:senha@exemplo.org/", "http://servidor.local/", "http://intranet.internal/",
    "https://", "exemplo.org",
])
def test_non_public_or_unsafe_addresses_are_refused(url: str) -> None:
    assert is_public_url(url) is False


def test_public_addresses_are_accepted_and_dns_to_private_ranges_is_refused() -> None:
    assert is_public_url("https://93.184.216.34/evento") is True
    assert is_public_url("https://evento.example.org/", lambda host: ["93.184.216.34"]) is True
    assert is_public_url("https://evento.example.org/", lambda host: ["10.1.2.3"]) is False  # nome que aponta para rede interna
    assert is_public_url("https://evento.example.org/", lambda host: []) is False  # não resolve: não acessar


def test_first_event_is_registered_once_inactive_and_without_invented_content(tmp_path) -> None:
    manager = make_manager(tmp_path, FakeWeb())
    ensure_first_event(manager)
    ensure_first_event(manager)  # idempotente
    events = manager.store.list_events()
    assert len(events) == 1 and events[0].name == "Robótica 2026" and events[0].state == "prepared"
    assert manager.store.active_id() is None
    texts = " ".join(i.content for i in manager.store.items(events[0].id))
    assert "23 de novembro de 2026" in texts and "Senac Paraíba" in texts
    allowed_words = FIRST_EVENT["description"] + FIRST_EVENT["name"]
    assert "palestra" not in texts.lower() and "oficina" not in texts.lower() and allowed_words


def test_first_event_is_not_registered_when_events_already_exist(tmp_path) -> None:
    manager = make_manager(tmp_path, FakeWeb())
    manager.create({"name": "Outro", "area": "A", "description": "D", "start_date": "2026-01-01", "end_date": "2026-01-02"})
    ensure_first_event(manager)
    assert [e.name for e in manager.store.list_events()] == ["Outro"]


def test_event_modules_do_not_write_conversations_or_visitor_data() -> None:
    """Privacidade: o pacote de eventos só grava dados de eventos (cadastro, fontes, itens, histórico, snapshots)."""
    for path in (ROOT / "backend" / "eventkb").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} | {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        assert not ({"session_id", "SessionContexts", "add_exchange"} & names), path.name


def test_the_event_package_is_not_imported_by_the_public_visitor_page() -> None:
    page = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    visitor = page[page.index('id="visitor"'):page.index('id="operator"')]
    assert "events-card" not in visitor and "event-dialog" not in visitor
    assert "/api/events" not in (ROOT / "frontend" / "conversation.js").read_text(encoding="utf-8")


def test_policy_still_protects_event_context_secrets() -> None:
    from backend.eventkb.knowledge import event_prompt_block  # noqa: PLC0415
    from backend.eventkb.models import Event  # noqa: PLC0415
    event = Event(id="e", name="E", area="A", description="D", start_date="2026-01-01", end_date="2026-01-02", notes="senha interna 123", reference_documents=["https://x.example.org/privado"])
    block = event_prompt_block(event)
    assert "senha interna" not in block and "privado" not in block  # observações e documentos não vão ao prompt
    assert real_kb()  # a base institucional segue disponível
