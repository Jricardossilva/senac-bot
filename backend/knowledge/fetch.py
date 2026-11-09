"""Consulta educada a páginas públicas: robots.txt, espaçamento entre requisições, redirecionamentos controlados.

Usada pelo atualizador da base institucional (domínios oficiais do Senac) e pelo Gerenciador de Eventos (domínios
informados pelo operador). Nunca acessa áreas autenticadas: 401/403 no robots.txt significa "não acessar".
"""
import logging
import time
import urllib.robotparser
from collections.abc import Callable
from urllib.parse import urljoin, urlparse

import httpx

logger = logging.getLogger("senac_bot.fetch")

MAX_REDIRECTS = 3
TIMEOUT_SECONDS = 15.0


class PoliteFetcher:
    def __init__(
        self,
        user_agent: str,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        delay: float = 2.5,
    ) -> None:
        self.user_agent = user_agent
        self.client = client or httpx.Client(
            timeout=TIMEOUT_SECONDS, headers={"User-Agent": user_agent, "Accept": "text/html"}, follow_redirects=False
        )
        self._sleep = sleep
        self._delay = delay
        self._robots: dict[str, urllib.robotparser.RobotFileParser | str] = {}
        self.requests = 0

    def get(self, url: str) -> httpx.Response:
        if self.requests:
            self._sleep(self._delay)  # espaça as requisições (sem coleta agressiva)
        self.requests += 1
        return self.client.get(url)

    def _robots_for(self, url: str) -> urllib.robotparser.RobotFileParser | str:
        """Parser do robots.txt da origem; ou 'unavailable' se não foi possível verificar (não acessar)."""
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin in self._robots:
            return self._robots[origin]
        parser = urllib.robotparser.RobotFileParser()
        try:
            response = self.get(origin + "/robots.txt")
        except httpx.HTTPError as error:
            logger.warning("robots.txt de %s inacessível (%s).", origin, type(error).__name__)
            self._robots[origin] = "unavailable"
            return "unavailable"
        if response.status_code in (401, 403):
            parser.disallow_all = True
        elif 400 <= response.status_code < 500:
            parser.allow_all = True
        elif response.status_code >= 500:
            self._robots[origin] = "unavailable"
            return "unavailable"
        else:
            parser.parse(response.text.splitlines())
        self._robots[origin] = parser
        return parser

    def allowed(self, url: str) -> tuple[bool, str]:
        robots = self._robots_for(url)
        if robots == "unavailable":
            return False, "robots.txt indisponível: não acessar sem verificar as regras do site"
        if not robots.can_fetch(self.user_agent, url):  # type: ignore[union-attr]
            return False, "bloqueado pelo robots.txt"
        return True, ""

    def fetch(self, url: str, url_ok: Callable[[str], bool], not_ok_reason: str = "endereço não permitido") -> tuple[httpx.Response | None, str]:
        """Baixa a página seguindo redirecionamentos dentro do que `url_ok` aceita. Devolve (resposta, motivo da recusa)."""
        for _ in range(MAX_REDIRECTS + 1):
            if not url_ok(url):
                return None, f"{not_ok_reason}: {url}"
            ok, reason = self.allowed(url)
            if not ok:
                return None, reason
            try:
                response = self.get(url)
            except httpx.HTTPError as error:
                return None, f"falha de rede ({type(error).__name__})"
            if response.status_code in (301, 302, 303, 307, 308) and response.headers.get("location"):
                url = urljoin(url, response.headers["location"])
                continue
            return response, ""
        return None, "redirecionamentos demais"
