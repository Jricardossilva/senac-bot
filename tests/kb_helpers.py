"""Utilitários de teste da base de conhecimento."""
from datetime import date
from pathlib import Path

from backend.knowledge import KnowledgeBase

KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent / "knowledge"
# Data fixa para os testes de atualidade (as notícias de março a maio de 2026 já estão vencidas nessa data).
TEST_TODAY = date(2026, 11, 7)


def real_kb(today: date = TEST_TODAY) -> KnowledgeBase:
    """Carrega a base real (arquivos do repositório), com a data de hoje fixada."""
    return KnowledgeBase.load(KNOWLEDGE_DIR, today=lambda: today)
