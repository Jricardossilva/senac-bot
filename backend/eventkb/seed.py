"""Primeiro evento cadastrado: Robótica 2026 (Senac Paraíba).

Só os dados que o projeto já registra (nome, período, organização, cidade). Nada de programação ou atividades é
inventado: o conhecimento do evento cresce quando o operador informa o site oficial e executa PESQUISAR E PREPARAR.
O evento nasce INATIVO; o operador decide quando ativar.
"""
import logging

from backend.eventkb.manager import EventManager

logger = logging.getLogger("senac_bot.eventkb.seed")

FIRST_EVENT = {
    "name": "Robótica 2026",
    "area": "Tecnologia e robótica",
    "description": "Evento do Senac Paraíba sobre tecnologia e robótica.",
    "start_date": "2026-11-23",
    "end_date": "2026-11-29",
    "organization": "Senac Paraíba",
    "city": "João Pessoa",
    "uf": "PB",
    "keywords": ["robótica", "programação", "inteligência artificial", "tecnologia"],
    "notes": "Cadastro inicial do projeto: informe o site oficial e a programação para enriquecer a base.",
}


def ensure_first_event(manager: EventManager) -> None:
    """Cadastra a Robótica 2026 na primeira execução (pasta de eventos vazia). Nunca sobrescreve nada."""
    try:
        if manager.store.list_events():
            return
        created = manager.create(FIRST_EVENT)
        manager.researcher.prepare(created["id"])  # sem site informado: só o cadastro vira conhecimento
        logger.info("Evento inicial cadastrado: %s.", created["name"])
    except Exception:  # noqa: BLE001 - o cadastro inicial nunca impede a aplicação de iniciar
        logger.exception("Não foi possível cadastrar o evento inicial.")
