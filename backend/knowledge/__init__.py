"""Base de conhecimento institucional do Senac (arquivos JSON em knowledge/)."""
from backend.knowledge.base import KnowledgeBase
from backend.knowledge.search import SearchResult

__all__ = ["KnowledgeBase", "SearchResult"]
