"""Utilitários dos testes do Gerenciador de Eventos: sites FICTÍCIOS (simulação) servidos por httpx.MockTransport."""
from pathlib import Path

import httpx

from backend.eventkb.models import Event
from backend.eventkb.research import EventResearcher
from backend.eventkb.store import EventStore
from backend.knowledge.fetch import PoliteFetcher

UA = "SENAC-BOT-Test/1.0"


class FakeWeb:
    """Internet de mentira: páginas HTML por URL, robots.txt configurável e contagem de requisições."""

    def __init__(self) -> None:
        self.pages: dict[str, str] = {}
        self.robots: dict[str, tuple[int, str]] = {}  # host -> (status, texto)
        self.status: dict[str, int] = {}
        self.requests: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.requests.append(url)
        if url.endswith("/robots.txt"):
            status, text = self.robots.get(request.url.host, (404, ""))
            return httpx.Response(status, text=text)
        if url in self.status:
            return httpx.Response(self.status[url], text="erro")
        if url in self.pages:
            return httpx.Response(200, text=self.pages[url], headers={"content-type": "text/html; charset=utf-8"})
        return httpx.Response(404, text="não encontrado")

    def factory(self):
        def make() -> PoliteFetcher:
            client = httpx.Client(transport=httpx.MockTransport(self.handler), headers={"User-Agent": UA})
            return PoliteFetcher(UA, client, sleep=lambda _: None, delay=0)
        return make


def make_researcher(store: EventStore, web: FakeWeb, discovery=None, today=None) -> EventResearcher:
    kwargs = {"today": today} if today else {}
    return EventResearcher(store, web.factory(), discovery=discovery, resolver=None, **kwargs)


def page(title: str, body: str, extra_head: str = "") -> str:
    return f"<html><head><title>{title}</title>{extra_head}</head><body><nav><a href='/menu'>Menu</a></nav>{body}<footer>Todos os direitos reservados</footer></body></html>"


# ---------------------------------------------------------------- três eventos FICTÍCIOS de áreas diferentes
ROBOTICA = dict(
    name="Robótica 2026", area="Tecnologia e robótica", description="Mostra de robótica, programação e inteligência artificial.",
    start_date="2026-11-23", end_date="2026-11-29", organization="Senac Paraíba", city="João Pessoa", uf="PB",
    website="https://robotica2026.example.org/", simulation=True,
)
GASTRONOMIA = dict(
    name="Feira de Gastronomia SIMULAÇÃO", area="Gastronomia e alimentação", description="Feira fictícia de teste sobre culinária e técnicas gastronômicas.",
    start_date="2026-09-10", end_date="2026-09-12", organization="Organização Fictícia de Gastronomia", city="Cidade Teste", uf="PB",
    website="https://feira-gastronomia.example.org/", simulation=True,
)
PROFISSOES = dict(
    name="Feira de Profissões SIMULAÇÃO", area="Educação e carreira", description="Feira fictícia de teste sobre carreiras e profissões.",
    start_date="2026-08-05", end_date="2026-08-06", organization="Organização Fictícia de Carreiras", city="Cidade Teste", uf="PB",
    website="https://feira-profissoes.example.org/", simulation=True,
)


def robotica_site(web: FakeWeb, horario: str = "14h", extra: str = "") -> None:
    web.pages["https://robotica2026.example.org/"] = page(
        "Robótica 2026 - Mostra de robótica",
        "<h1>Robótica 2026</h1><p>A Robótica 2026 reúne escolas, estudantes e empresas para mostrar projetos de robótica e programação.</p>"
        "<h2>Local</h2><p>O evento acontece no CEP João Pessoa, na Avenida Dom Pedro I, 389, Centro.</p>"
        "<h2>Datas</h2><p>A Robótica 2026 acontece de 23 a 29 de novembro de 2026, com visitação das 9h às 17h.</p>"
        "<a href='/programacao'>Veja a programação completa</a><a href='/visite'>Informações para visitantes</a>" + extra,
        extra_head="<meta name='description' content='Mostra de robótica e programação em João Pessoa.'>",
    )
    web.pages["https://robotica2026.example.org/programacao"] = page(
        "Programação - Robótica 2026",
        "<h2>Programação</h2>"
        f"<p>Dia 24/11 às {horario}: oficina de robótica com Arduino para iniciantes, com vagas limitadas ao auditório.</p>"
        "<p>Dia 25/11 às 10h: palestra sobre inteligência artificial e o futuro do trabalho com a equipe do evento.</p>"
        "<h2>Competição</h2><p>A competição de robôs seguidores de linha acontece no dia 27/11 e é aberta a equipes escolares.</p>",
    )
    web.pages["https://robotica2026.example.org/visite"] = page(
        "Visite - Robótica 2026",
        "<h2>Informações para visitantes</h2><p>A entrada na Robótica 2026 é gratuita e não é necessário se inscrever para visitar a mostra.</p>"
        "<h2>Perguntas frequentes</h2><p>Preciso pagar ingresso para ver a Robótica 2026?</p><p>Não: a visitação é gratuita durante todos os dias do evento.</p>",
    )


def gastronomia_site(web: FakeWeb) -> None:
    web.pages["https://feira-gastronomia.example.org/"] = page(
        "Feira de Gastronomia SIMULAÇÃO",
        "<h1>Feira de Gastronomia SIMULAÇÃO</h1><p>A Feira de Gastronomia SIMULAÇÃO é um evento fictício de teste sobre culinária, técnicas gastronômicas e alimentação.</p>"
        "<h2>Datas</h2><p>A Feira de Gastronomia acontece de 10 a 12 de setembro de 2026 no Pavilhão Fictício.</p>"
        "<h2>Programação</h2><p>Dia 11/09 às 15h: oficina de massas frescas e molhos com um chef convidado fictício.</p>"
        "<h2>Atividades</h2><p>A mostra de sobremesas regionais acontece todos os dias, com degustação para os visitantes da Feira de Gastronomia.</p>",
    )


def profissoes_site(web: FakeWeb) -> None:
    web.pages["https://feira-profissoes.example.org/"] = page(
        "Feira de Profissões SIMULAÇÃO",
        "<h1>Feira de Profissões SIMULAÇÃO</h1><p>A Feira de Profissões SIMULAÇÃO é um evento fictício de teste sobre carreiras, áreas de atuação e oportunidades educacionais.</p>"
        "<h2>Datas</h2><p>A Feira de Profissões acontece de 5 a 6 de agosto de 2026 no Ginásio Fictício.</p>"
        "<h2>Programação</h2><p>Dia 05/08 às 9h: roda de conversa sobre escolha de carreira com profissionais convidados fictícios.</p>"
        "<h2>Atividades</h2><p>Os estandes de orientação profissional apresentam cursos, profissões e áreas de atuação aos visitantes.</p>",
    )


def new_store(tmp_path: Path) -> EventStore:
    return EventStore(tmp_path / "events")


def create(store: EventStore, data: dict) -> Event:
    return store.create(data)


def make_manager(tmp_path: Path, web: FakeWeb, discovery=None, clock=None):
    """Gerenciador de eventos de teste: pesquisa síncrona, sites fictícios, aliases da base institucional real."""
    from datetime import date

    from backend.eventkb.manager import EventManager
    from tests.kb_helpers import real_kb

    store = new_store(tmp_path)
    researcher = make_researcher(store, web, discovery)
    kwargs = {"clock": clock} if clock else {}
    return EventManager(store, researcher, aliases=real_kb().aliases, today=lambda: date(2026, 11, 25), run_in_thread=False, **kwargs)


def prepared(manager, data: dict) -> str:
    """Cadastra, pesquisa (síncrono) e devolve o id do evento."""
    event = manager.create(data)
    manager.start_research(event["id"], "prepare")
    return event["id"]
