"""Consulta educada a páginas públicas: robots.txt, espaçamento entre requisições, redirecionamentos controlados.

Usada pelo atualizador da base institucional (domínios oficiais do Senac) e pelo Gerenciador de Eventos (domínios
informados pelo operador). Nunca acessa áreas autenticadas: 401/403 no robots.txt significa "não acessar".
"""
import ipaddress
import logging
import time
import urllib.robotparser
from collections.abc import Callable
from urllib.parse import urljoin, urlparse

import httpx

logger = logging.getLogger("senac_bot.fetch")

MAX_REDIRECTS = 3
TIMEOUT_SECONDS = 15.0


def _internal_peer(response: httpx.Response) -> str | None:
    """Endereço IP interno ao qual a conexão realmente se ligou (None = público ou desconhecido).

    Segunda barreira contra SSRF/DNS rebinding: o nome pode ter resolvido para um IP público na checagem prévia e para um
    interno na conexão. Se o IP real for interno, a resposta é descartada e nunca chega ao conteúdo da pesquisa."""
    try:
        stream = response.extensions.get("network_stream")
        info = stream.get_extra_info("server_addr") if stream is not None else None
        ip = ipaddress.ip_address(str(info[0]).split("%")[0]) if info else None
    except (AttributeError, IndexError, TypeError, ValueError, OSError):
        return None
    if ip is None:
        return None
    if getattr(ip, "ipv4_mapped", None) is not None:
        ip = ip.ipv4_mapped
    internal = ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified
    return str(ip) if internal else None


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
            if _internal_peer(response) is not None:
                logger.warning("Conexão para %s terminou em endereço interno; resposta descartada.", url)
                return None, "endereço não permitido (a conexão levou a uma rede interna)"
            if response.status_code in (301, 302, 303, 307, 308) and response.headers.get("location"):
                url = urljoin(url, response.headers["location"])
                continue
            return response, ""
        return None, "redirecionamentos demais"
