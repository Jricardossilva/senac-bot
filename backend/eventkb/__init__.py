"""Gerenciador de Eventos: conhecimento dinâmico por evento (camada 2), pesquisa e validação."""
from backend.eventkb.knowledge import EventKnowledge, event_prompt_block
from backend.eventkb.manager import EventManager
from backend.eventkb.models import Event, EventItem, EventSource
from backend.eventkb.research import EventResearcher, is_public_url
from backend.eventkb.store import EventStore, EventStoreError

__all__ = ["Event", "EventItem", "EventKnowledge", "EventManager", "EventResearcher", "EventSource", "EventStore", "EventStoreError", "event_prompt_block", "is_public_url"]
