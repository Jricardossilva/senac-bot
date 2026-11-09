"""Descoberta opcional do site oficial de um evento (camada 3 aplicada ao preparo).

Usa a pesquisa do provedor de IA. O resultado são apenas ENDEREÇOS CANDIDATOS: nada vindo daqui é confirmado. O
pesquisador baixa as páginas com educação (robots.txt), confere se falam do evento e, mesmo assim, o conteúdo só
chega ao visitante depois que o operador confirmar a fonte ou aprovar os itens.
"""
import logging
import re
from collections.abc import Callable

from backend.ai.base import AIProvider
from backend.eventkb.models import Event

logger = logging.getLogger("senac_bot.eventkb.discovery")
_URL = re.compile(r"https://[^\s)>\]\"'<,;]+")


def make_discovery(provider: AIProvider) -> Callable[[Event], list[str]] | None:
    if not provider.is_configured():
        return None

    def discover(event: Event) -> list[str]:
        where = " ".join(p for p in (event.organization, event.city, event.uf) if p)
        query = (f"Qual é o site oficial do evento \"{event.name}\" ({event.area}) {where}? "
                 "Responda somente com até 3 endereços https de sites oficiais, um por linha. Se não souber, responda: não encontrei.")
        answer = provider.search(query, None)
        urls: list[str] = []
        for url in _URL.findall(answer.text):
            url = url.rstrip(".")
            if url not in urls and "google.com" not in url:
                urls.append(url)
        return urls[:3]

    return discover
