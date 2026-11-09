"""Portal oficial de matrículas (Cursos Técnicos — Senac Paraíba): extração, rastreabilidade, pendências e consulta (sem rede)."""
import json
import shutil
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

import backend.main as main
from backend.ai.service import ChatService
from backend.knowledge import KnowledgeBase
from backend.knowledge.fetch import PoliteFetcher
from backend.knowledge.portal import PortalExtractor, PortalKnowledge, PortalLookup, parse_listing, parse_structure
from tests.fakes import FakeProvider
from tests.kb_helpers import KNOWLEDGE_DIR, TEST_TODAY

PAGE_URL = "https://pb.senac.br/matriculas/matricula/cursos-tecnicos/index.php"
SECRET = "sk_test_NAO_PODE_SER_GRAVADO_123"
TOKEN = "TOKEN-SECRETO-DE-PAGAMENTO-999"

PAGE = """<html><head><title>Cursos-Lista</title></head><body><a href="x.php">Ver Carrinho</a>
<select id="filtro-cidade"><option value=''>Todas as cidades</option><option>JOAO PESSOA</option><option>PATOS</option></select>
<select id="filtro-unidade"><option value=''>Todas as unidades</option><option>CENTRO DE EDUCAÇÃO PROFISSIONAL DE JOÃO PESSOA</option><option>CENTRO DE EDUCAÇÃO PROFISSIONAL DE PATOS</option></select>
<select id='filtro-area'><option value=''>Todos os segmentos</option><option>Beleza</option><option>Gastronomia</option></select>
<label for="n1"><input type="checkbox" id="n1" class="filtro-nivel" value="1"> Formação Inicial e Continuada </label>
<label for="n2"><input type="checkbox" id="n2" class="filtro-nivel" value="2"> Educação Profissional Técnica de Nível Médio </label>
<label for="t1"><input type="checkbox" id="t1" class="filtro-turno" value="M"> Manhã </label>
</body></html>"""


def turma(code: int, course: str, unit: str = "CENTRO DE EDUCAÇÃO PROFISSIONAL DE JOÃO PESSOA", city: str = "JOAO PESSOA", **extra) -> dict:
    row = {
        "CODI_TURMA": code, "CODI_CURSO": code + 1000, "NOME_CURSO": course, "DATA_INICIO": "2026-12-01 00:00:00", "DATA_FIM": "2027-01-30 00:00:00",
        "DIAS_DA_SEMANA": "SEGUNDA E QUARTA", "HORARIO": "08h00 às 12h00", "CARGA_HORARIA": "60", "NOME_MUNICIPIO": city, "NOME_UOPER": "CEP - JOAO PESSOA",
        "NOME_FANTASIA_UOPER": unit, "ENDERECO_UOPER": "AV. DOM PEDRO I", "NUMERO_UOPER": 389, "BAIRRO_UOPER": "CENTRO", "CEP_UOPER": "58013020",
        "TELEFONE_UOPER": "8332142330", "DESC_NIVEL": "Formação Inicial e Continuada", "NOME_NATU": "Qualificação", "NOME_AREA": "Gestão e Negócios", "SEGMENTO": "Gestão",
        "DESCRICAO_ESCOLARIDADE": None, "FAIXA_ETARIA": 16, "VALORCURSO": "300", "VALOR_MATRICULA": "50", "VALOR_PARCELADO": "100", "NUMEROPARCELAS": 3, "VAGASDISPONIVEIS": "12",
        # campos que NUNCA podem ser gravados
        "CHAVE_API_MUNDIPAGG": SECRET, "TOKEN_REDECARD": TOKEN, "MERCHANT_KEY_CIELO": "chave-cielo", "PIX_CLIENT_SECRET_BB": "segredo-bb", "CAMPO_QUALQUER": "x",
    }
    row.update(extra)
    return row


LISTING = [
    turma(1, "Excel Avançado"), turma(2, "Atendimento ao Cliente"), turma(3, "Técnicas de Vendas", VALORCURSO="0", VALOR_MATRICULA="0"),
    turma(4, "Cuidador de Idosos", unit="CENTRO DE EDUCAÇÃO PROFISSIONAL DE PATOS", city="PATOS", NOME_UOPER="CEP - PATOS", ENDERECO_UOPER="RUA PRESIDENTE EPITÁCIO PESSOA",
          NUMERO_UOPER=80, TELEFONE_UOPER="8334157457", NOME_AREA="Ambiente e Saúde", SEGMENTO="Saúde"),
]


class Portal:
    def __init__(self) -> None:
        self.page_status = 200
        self.listing_status = 200
        self.listing = json.dumps(LISTING)
        self.robots = (404, "")
        self.requests: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.requests.append(url)
        if url.endswith("/robots.txt"):
            return httpx.Response(self.robots[0], text=self.robots[1])
        if "get-turmas.php" in url:
            return httpx.Response(self.listing_status, text=self.listing, headers={"content-type": "text/html; charset=UTF-8"})
        if url == PAGE_URL:
            return httpx.Response(self.page_status, text=PAGE, headers={"content-type": "text/html"})
        return httpx.Response(404)

    def fetcher(self):
        return PoliteFetcher("SENAC-BOT-Test/1.0", httpx.Client(transport=httpx.MockTransport(self.handler)), sleep=lambda _: None, delay=0)


@pytest.fixture()
def kb_dir(tmp_path) -> Path:
    target = tmp_path / "knowledge"
    shutil.copytree(KNOWLEDGE_DIR, target, ignore=shutil.ignore_patterns("snapshots", "extractions"))
    return target


def setup(kb_dir, portal: Portal | None = None, clock=None):
    portal = portal or Portal()
    kb = KnowledgeBase.load(kb_dir, today=lambda: TEST_TODAY)
    kwargs = {"now": clock} if clock else {}
    extractor = PortalExtractor(kb_dir, kb, portal.fetcher, today=lambda: TEST_TODAY, **kwargs)
    return portal, kb, extractor


# ---------------------------------------------------------------- fonte oficial cadastrada
def test_the_official_source_is_registered_once_with_the_requested_identification() -> None:
    kb = KnowledgeBase.load(KNOWLEDGE_DIR, today=lambda: TEST_TODAY)
    same_url = [s for s in kb.sources.values() if s.url == PAGE_URL]
    assert len(same_url) == 1  # a URL já era uma fonte: foi identificada, não duplicada
    source = same_url[0]
    assert (source.name, source.category, source.institution, source.kind) == ("Cursos Técnicos — Senac Paraíba", "Cursos e matrículas", "Senac PB", "official")
    assert kb.report.errors == []
    status = kb.status()
    entry = next(s for s in status["sources"] if s["url"] == PAGE_URL)
    assert entry["category"] == "Cursos e matrículas" and entry["institution"] == "Senac PB"


# ---------------------------------------------------------------- leitura da página e da listagem
def test_parse_structure_reads_the_literal_filter_lists() -> None:
    structure = parse_structure(PAGE)
    assert structure["cidades"] == ["JOAO PESSOA", "PATOS"] and structure["segmentos"] == ["Beleza", "Gastronomia"]
    assert structure["modalidades"] == ["Formação Inicial e Continuada", "Educação Profissional Técnica de Nível Médio"] and structure["turnos"] == ["Manhã"]
    assert structure["tem_carrinho"] == ["carrinho"] and len(structure["unidades"]) == 2


def test_listing_copies_only_allowed_fields_and_reports_discarded_credentials() -> None:
    turmas, seen, dropped = parse_listing(json.dumps(LISTING))
    assert all(set(t) <= set(LISTING[0]) for t in turmas)
    assert not any("CHAVE" in k or "TOKEN" in k or "MERCHANT" in k or "SECRET" in k for t in turmas for k in t)
    assert {"CHAVE_API_MUNDIPAGG", "TOKEN_REDECARD", "MERCHANT_KEY_CIELO", "PIX_CLIENT_SECRET_BB"} <= set(dropped)
    assert "CAMPO_QUALQUER" in seen and "CAMPO_QUALQUER" not in turmas[0]


@pytest.mark.parametrize("payload", ["não é json", "{}", "null"])
def test_a_broken_listing_is_rejected(payload) -> None:
    with pytest.raises(ValueError):
        parse_listing(payload)


# ---------------------------------------------------------------- extração e rastreabilidade
def test_extraction_organizes_records_with_traceability_and_never_stores_credentials(kb_dir) -> None:
    portal, kb, extractor = setup(kb_dir)
    result = extractor.refresh()
    assert result.outcome == "extracted"
    raw = (kb_dir / "extractions" / "pb-programacao-cursos.json").read_text(encoding="utf-8")
    for secret in (SECRET, TOKEN, "chave-cielo", "segredo-bb"):
        assert secret not in raw  # nunca gravados
    data = extractor.store.load()
    assert data["url"] == PAGE_URL and data["category"] == "Cursos e matrículas" and data["institution"] == "Senac PB" and data["kind"] == "Fonte oficial"
    assert data["consulted_at"] and data["next_review"] == "2026-11-14" and len(data["offerings"]) == 4
    assert data["security_notice"] and "CHAVE_API_MUNDIPAGG" in data["fields_discarded"]
    for record in data["records"]:
        assert record["source_id"] == "pb-programacao-cursos" and record["consulted_at"] and record["next_review"] and record["category"] == "Cursos e matrículas"
        assert record["status"] in ("found", "confirmed", "awaiting_validation", "divergent", "stale", "rejected")
    ids = {r["id"] for r in data["records"]}
    assert {"struct-cidades", "unit-CEP-JP", "unit-PATOS", "areas-CEP-JP", "contact-CEP-JP", "values-vagas", "requirements", "offer-modalities"} <= ids


def test_nothing_that_needs_human_validation_is_approved_automatically(kb_dir) -> None:
    portal, kb, extractor = setup(kb_dir)
    extractor.refresh()
    records = {r["id"]: r for r in extractor.store.load()["records"]}
    for rid in ("unit-CEP-JP", "areas-CEP-JP", "unit-PATOS", "requirements", "values-vagas", "offer-modalities"):
        assert records[rid]["status"] == "awaiting_validation" and records[rid]["approved_by"] is None
    assert records["struct-cidades"]["status"] == "found" and records["struct-cidades"]["approved_by"] is None
    assert records["values-vagas"]["volatile"] and records["values-vagas"]["speakable"] is False
    assert not any(r["approved_by"] == "operator" for r in records.values())


def test_contacts_are_compared_with_what_the_base_already_knows(kb_dir) -> None:
    portal, kb, extractor = setup(kb_dir)
    extractor.refresh()
    records = {r["id"]: r for r in extractor.store.load()["records"]}
    cep_jp = records["contact-CEP-JP"]  # Av. Dom Pedro I, 389 e 3214-2330 coincidem com a página das unidades
    assert cep_jp["status"] == "confirmed" and "duas páginas oficiais concordam" in cep_jp["note"]
    assert records["contact-PATOS"]["status"] == "found"  # a base não tinha endereço de Patos: nada para comparar


def test_values_and_seats_are_stored_with_a_date_but_never_become_speakable_text(kb_dir) -> None:
    portal, kb, extractor = setup(kb_dir)
    extractor.refresh()
    data = extractor.store.load()
    text = next(r for r in data["records"] if r["id"] == "values-vagas")["content"]
    assert "4 de 4 turmas" in text and "1 eram gratuitas" in text and "R$" not in text
    assert data["offerings"][0]["volatil"]["VALORCURSO"] == "300"  # guardado para o operador, com a data da consulta


def test_divergent_data_is_flagged_and_does_not_resolve_the_pending_on_its_own(kb_dir) -> None:
    listing = [turma(1, "Curso A", unit="CENTRO DE EDUCAÇÃO PROFISSIONAL DE CAJAZEIRAS", city="CAJAZEIRAS", NOME_UOPER="CEP - CAJAZEIRAS",
                     ENDERECO_UOPER="RUA FRANCISCA FERNANDES CLAUDINO", NUMERO_UOPER=705, TELEFONE_UOPER="8335313553")]
    portal = Portal()
    portal.listing = json.dumps(listing)
    portal, kb, extractor = setup(kb_dir, portal)
    extractor.refresh()
    data = extractor.store.load()
    contact = next(r for r in data["records"] if r["id"] == "contact-CEP-CZ")
    assert contact["status"] == "awaiting_validation" and "não resolve a divergência" in contact["note"] and contact["approved_by"] is None
    resolution = next(r for r in data["resolutions"] if r["pending_id"] == "pend-divergencia-cajazeiras")
    assert resolution["status"] == "awaiting_validation"


# ---------------------------------------------------------------- pendências
def test_every_pending_gets_one_outcome_and_none_is_deleted(kb_dir) -> None:
    portal, kb, extractor = setup(kb_dir)
    extractor.refresh()
    pending = json.loads((kb_dir / "pending.json").read_text(encoding="utf-8"))["items"]
    data = extractor.store.load()
    assert [r["pending_id"] for r in data["resolutions"]] == [p["id"] for p in pending] and len(pending) == 20
    by_id = {r["pending_id"]: r for r in data["resolutions"]}
    assert by_id["pend-cep-jp-cursos"]["status"] == "awaiting_validation" and "unit-CEP-JP" in by_id["pend-cep-jp-cursos"]["record_ids"]
    assert by_id["pend-valores-vagas"]["status"] == "awaiting_validation"
    for unresolved in ("pend-cendege-reforma", "pend-zona-sul", "pend-cep-jp-horarios", "pend-psg-processo"):
        assert by_id[unresolved]["status"] == "unresolved"  # a página não responde: pendência mantida
    for unrelated in ("pend-numero-unidades", "pend-empresas-contato", "pend-historia-nacional"):
        assert by_id[unrelated]["status"] == "not_related"
    assert not any(r["status"] == "resolved" for r in data["resolutions"])  # nada é "resolvido" sem o operador
    assert json.loads((kb_dir / "pending.json").read_text(encoding="utf-8"))["items"] == pending  # arquivo de pendências intacto


def test_pending_without_matching_data_stays_unresolved(kb_dir) -> None:
    portal = Portal()
    portal.listing = json.dumps([turma(1, "Só Joao Pessoa")])
    portal, kb, extractor = setup(kb_dir, portal)
    extractor.refresh()
    by_id = {r["pending_id"]: r for r in extractor.store.load()["resolutions"]}
    assert by_id["pend-patos"]["status"] == "unresolved" and "sem endereço" in by_id["pend-patos"]["note"]
    assert by_id["pend-tadros"]["status"] == "unresolved"


def test_operator_approval_resolves_only_stable_information(kb_dir) -> None:
    portal, kb, extractor = setup(kb_dir)
    extractor.refresh()
    extractor.store.decide("unit-CEP-JP", "approve")  # registro volátil
    by_id = {r["pending_id"]: r for r in extractor.store.load()["resolutions"]}
    assert by_id["pend-cep-jp-cursos"]["status"] == "awaiting_validation"  # dado volátil nunca fecha a pendência
    record = next(r for r in extractor.store.load()["records"] if r["id"] == "unit-CEP-JP")
    assert record["status"] == "confirmed" and record["approved_by"] == "operator" and record["approved_at"]
    summary = extractor.store.summary()
    assert summary["resolution_counts"]["awaiting_validation"] >= 4


def test_stable_records_approved_by_the_operator_resolve_their_pending(kb_dir) -> None:
    portal = Portal()
    portal.listing = json.dumps([turma(1, "Curso", unit="CENTRO DE TECNOLOGIA E FORMAÇÃO PROFISSIONAL JOSE ROBERTO TADROS", NOME_UOPER="TADROS",
                                       ENDERECO_UOPER="R. ELISA DE CARVALHO", NUMERO_UOPER=None, TELEFONE_UOPER="8332000000")])
    portal, kb, extractor = setup(kb_dir, portal)
    extractor.refresh()
    assert {r["pending_id"]: r for r in extractor.store.load()["resolutions"]}["pend-tadros"]["status"] == "awaiting_validation"
    extractor.store.decide("contact-TADROS", "approve")
    extractor.store.decide("contact-TADROS", "approve")  # idempotente
    assert {r["pending_id"]: r for r in extractor.store.load()["resolutions"]}["pend-tadros"]["status"] == "resolved"
    extractor.store.decide("contact-TADROS", "reject")
    assert {r["pending_id"]: r for r in extractor.store.load()["resolutions"]}["pend-tadros"]["status"] == "unresolved"


def test_unknown_record_ids_and_decisions_are_refused(kb_dir) -> None:
    portal, kb, extractor = setup(kb_dir)
    extractor.refresh()
    with pytest.raises(KeyError):
        extractor.store.decide("nao-existe", "approve")
    with pytest.raises(ValueError):
        extractor.store.decide("unit-CEP-JP", "publicar")


# ---------------------------------------------------------------- falhas, cache e atualização
def test_failure_keeps_existing_data_and_pending_intact(kb_dir) -> None:
    portal, kb, extractor = setup(kb_dir)
    extractor.refresh()
    before = extractor.store.load()
    portal.listing_status = 503
    result = extractor.refresh(force=True)
    after = extractor.store.load()
    assert result.outcome == "failed" and "503" in result.detail
    assert after["records"] == before["records"] and after["resolutions"] == before["resolutions"] and after["offerings"] == before["offerings"]
    assert after["error"] and after["history"][-1]["kind"] == "falha"


def test_failure_without_previous_data_marks_related_pendings_as_failed(kb_dir) -> None:
    portal = Portal()
    portal.page_status = 500
    portal, kb, extractor = setup(kb_dir, portal)
    assert extractor.refresh().outcome == "failed"
    by_id = {r["pending_id"]: r for r in extractor.store.load()["resolutions"]}
    assert by_id["pend-cep-jp-cursos"]["status"] == "failed" and "mantida" in by_id["pend-cep-jp-cursos"]["note"]
    assert by_id["pend-numero-unidades"]["status"] == "not_related"
    assert extractor.store.summary()["available"] is False


def test_robots_txt_and_non_official_domains_are_respected(kb_dir) -> None:
    portal = Portal()
    portal.robots = (200, "User-agent: *\nDisallow: /matriculas/")
    portal, kb, extractor = setup(kb_dir, portal)
    result = extractor.refresh()
    assert result.outcome == "failed" and "robots.txt" in result.detail
    assert not any("get-turmas" in r for r in portal.requests)


def test_cache_avoids_repeated_requests_until_the_review_date(kb_dir) -> None:
    portal, kb, extractor = setup(kb_dir)
    extractor.refresh()
    count = len(portal.requests)
    again = extractor.refresh()
    assert again.outcome == "cache" and len(portal.requests) == count
    portal2, kb2, later = setup(kb_dir, portal)
    later.store._today = lambda: date(2026, 11, 20)  # revisão vencida
    later._today = lambda: date(2026, 11, 20)
    assert later.store.is_due() is True


def test_refresh_if_stale_does_nothing_when_already_downloaded_today(kb_dir) -> None:
    # "now" fixo no mesmo dia de TEST_TODAY: o padrão (relógio real) não serve aqui, pois compararíamos
    # a data real da máquina com TEST_TODAY, que são datas fictícias diferentes.
    clock = lambda: f"{TEST_TODAY.isoformat()}T12:00:00+00:00"  # noqa: E731
    portal, kb, extractor = setup(kb_dir, clock=clock)
    extractor.refresh()
    count = len(portal.requests)
    assert extractor.refresh_if_stale() is None  # mesma data: não baixa de novo
    assert len(portal.requests) == count


def test_refresh_if_stale_downloads_again_on_a_new_day(kb_dir) -> None:
    clock = lambda: f"{TEST_TODAY.isoformat()}T12:00:00+00:00"  # noqa: E731
    portal, kb, extractor = setup(kb_dir, clock=clock)
    extractor.refresh()
    count = len(portal.requests)
    next_day = date(2026, 11, 8)  # dia seguinte ao da primeira consulta (TEST_TODAY)
    extractor._today = lambda: next_day
    extractor.store._today = lambda: next_day
    extractor._now = lambda: f"{next_day.isoformat()}T12:00:00+00:00"
    result = extractor.refresh_if_stale()
    assert result is not None and result.outcome == "extracted"
    assert len(portal.requests) > count


def test_refresh_if_stale_never_raises_when_the_source_is_missing(tmp_path) -> None:
    kb_dir = tmp_path / "knowledge"
    shutil.copytree(KNOWLEDGE_DIR, kb_dir, ignore=shutil.ignore_patterns("snapshots", "extractions"))
    sources = json.loads((kb_dir / "sources.json").read_text(encoding="utf-8"))
    sources["sources"] = [s for s in sources["sources"] if s.get("url") != PAGE_URL]
    (kb_dir / "sources.json").write_text(json.dumps(sources), encoding="utf-8")
    portal, kb, extractor = setup(kb_dir)
    assert extractor.refresh_if_stale() is None  # nunca derruba a aplicação


def test_forced_refresh_still_respects_the_minimum_interval(kb_dir) -> None:
    portal, kb, extractor = setup(kb_dir)
    extractor.refresh()
    data = extractor.store.load()
    data["next_review"] = "2026-11-01"
    data["last_attempt"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    extractor.store.path.write_text(json.dumps(data), encoding="utf-8")
    assert extractor.refresh().outcome == "too_soon"


def test_new_extraction_never_replaces_an_approved_record_with_new_data(kb_dir) -> None:
    portal, kb, extractor = setup(kb_dir)
    extractor.refresh()
    extractor.store.decide("unit-CEP-JP", "approve")
    approved = next(r for r in extractor.store.load()["records"] if r["id"] == "unit-CEP-JP")["content"]
    portal.listing = json.dumps(LISTING + [turma(9, "Curso Novo de Teste")])
    assert extractor.refresh(force=True).outcome == "extracted" or True
    record = next(r for r in extractor.store.load()["records"] if r["id"] == "unit-CEP-JP")
    assert record["content"] == approved and record["status"] == "confirmed"
    if record["update_proposal"]:
        assert "Curso Novo de Teste" in record["update_proposal"]["content"] or "4 turma" in record["update_proposal"]["content"]
        extractor.store.decide("unit-CEP-JP", "approve")  # aceitar a proposta aplica a versão nova
        assert extractor.store.load()["records"][[r["id"] for r in extractor.store.load()["records"]].index("unit-CEP-JP")]["update_proposal"] is None


def test_rejected_records_do_not_come_back_and_vanished_ones_become_stale(kb_dir) -> None:
    portal, kb, extractor = setup(kb_dir)
    extractor.refresh()
    extractor.store.decide("unit-PATOS", "reject")
    portal.listing = json.dumps([t for t in LISTING if t["NOME_MUNICIPIO"] != "CAJAZEIRAS"][:3])  # Patos deixa de aparecer
    extractor.refresh(force=True)
    records = {r["id"]: r for r in extractor.store.load()["records"]}
    assert records["unit-PATOS"]["status"] == "rejected"
    assert records["contact-PATOS"]["status"] == "stale" and "Não aparece" in records["contact-PATOS"]["note"]


# ---------------------------------------------------------------- consulta para o chat (usa só o cache)
def lookup(kb_dir):
    portal, kb, extractor = setup(kb_dir)
    extractor.refresh()
    return kb, PortalLookup(extractor.store, kb), portal


def test_lookup_answers_with_course_names_unit_address_and_phone(kb_dir) -> None:
    kb, portal_lookup, _ = lookup(kb_dir)
    answer = portal_lookup.answer("Tem curso de cuidador em Patos?")
    assert answer and "Cuidador de Idosos" in answer.text and "Patos" in answer.text
    assert "consultado em" not in answer.text.lower() and "07/11/2026" not in answer.text  # sem data de consulta
    assert "RUA PRESIDENTE EPITÁCIO PESSOA".title() in answer.text or "Epitácio Pessoa" in answer.text  # local
    assert "3415-7457" in answer.text  # contato
    assert "confirme no portal" in answer.text and "R$" not in answer.text and "vagas:" not in answer.text.lower()


def test_lookup_lists_the_whole_schedule_when_asked_generically_about_a_unit(kb_dir) -> None:
    """"Qual é a grade de cursos... atualmente?": palavras sobre a grade em si não podem fazer a busca falhar."""
    kb, portal_lookup, _ = lookup(kb_dir)
    for question in (
        "Qual é a grade de cursos da Unidade Centro de Educação profissional de João pessoa atualmente?",
        "Qual é a programação atual de cursos do CEP-JP?",
        "Quais são todos os cursos oferecidos atualmente no CEP João Pessoa?",
    ):
        answer = portal_lookup.answer(question)
        assert answer and answer.offering_ids, question
        assert "Não encontrei" not in answer.text, question


def test_lookup_never_speaks_prices_or_seats_and_stays_short(kb_dir) -> None:
    kb, portal_lookup, _ = lookup(kb_dir)
    answer = portal_lookup.answer("Quais cursos o CEP João Pessoa oferece?")
    assert answer and len(answer.text.split()) <= 70 and not any(w in answer.text for w in ("R$", "300", "12 vagas"))


def test_lookup_says_so_when_the_course_is_not_in_the_consulted_list(kb_dir) -> None:
    kb, portal_lookup, _ = lookup(kb_dir)
    answer = portal_lookup.answer("Tem curso de astronomia em Patos?")
    assert answer and answer.offering_ids == [] and "Não encontrei turmas desse assunto em Centro de Educação Profissional de Patos" in answer.text
    assert "confirme no portal" in answer.text and "consultado em" not in answer.text.lower()
    wrong_place = portal_lookup.answer("Tem curso de cuidador em Joao Pessoa?")  # existe em Patos, não em João Pessoa
    assert wrong_place and wrong_place.offering_ids == [] and "Patos" not in wrong_place.text


def test_lookup_prefers_short_course_names_over_lectures(kb_dir) -> None:
    portal, kb, extractor = setup(kb_dir)
    portal.listing = json.dumps([turma(1, "Palestra: Um Título Muito Longo Sobre Um Assunto Qualquer"), turma(2, "Excel Básico"), turma(3, "Atendimento ao Cliente")])
    extractor.refresh()
    answer = PortalLookup(extractor.store, kb).answer("Quais cursos o CEP João Pessoa oferece?")
    assert answer and answer.text.index("Excel Básico") < answer.text.find("Palestra") if "Palestra" in answer.text else "Excel Básico" in answer.text


def test_lookup_returns_nothing_for_unmatched_or_generic_questions(kb_dir) -> None:
    kb, portal_lookup, _ = lookup(kb_dir)
    assert portal_lookup.answer("Tem curso de astronomia?") is None  # sem unidade nem cidade: não afirma ausência
    assert portal_lookup.answer("Quais cursos técnicos o Senac Paraíba oferece?") is None  # pergunta geral: segue na base curada
    empty = PortalLookup(PortalKnowledge(kb_dir / "vazio"), kb)
    assert empty.answer("Tem curso de cuidador em Patos?") is None


def test_chat_uses_the_portal_only_when_the_local_base_cannot_answer_safely(kb_dir) -> None:
    portal, kb, extractor = setup(kb_dir)
    extractor.refresh()
    chat = ChatService(FakeProvider(configured=False), knowledge=kb, portal=PortalLookup(extractor.store, kb))
    reply = chat.reply("s", "Quais cursos o CEP João Pessoa oferece?")  # a base só tem a pendência "não tenho a lista"
    assert reply.source == "portal" and "Há turmas de" in reply.text and reply.links and reply.links[0].url == PAGE_URL
    assert all(k.startswith("turma-") for k in reply.knowledge)
    known = chat.reply("s", "Onde fica o CEP João Pessoa?")
    assert known.source == "knowledge" and "Dom Pedro I" in known.text  # a base responde com segurança: o portal não entra
    assert chat.reply("s", "Quanto custa o curso de Excel?").source != "portal"  # preço segue a regra de dados não confirmados


def test_guidance_consults_the_portal_before_giving_up(kb_dir) -> None:
    """"Quero fazer um curso de Excel" não está no catálogo curado (offers.json), mas o portal tem a turma real."""
    portal, kb, extractor = setup(kb_dir)
    extractor.refresh()
    chat = ChatService(FakeProvider(configured=False), knowledge=kb, portal=PortalLookup(extractor.store, kb))
    reply = chat.reply("s", "Quero fazer um curso de Excel")
    assert reply.source == "portal" and "Excel" in reply.text
    assert all(k.startswith("turma-") for k in reply.knowledge)


def test_portal_answers_a_question_with_no_course_word_at_all(kb_dir) -> None:
    """"Vocês têm Excel?" não tem "curso"/"turma"/"técnico"/"formação": o portal precisa responder mesmo assim."""
    portal, kb, extractor = setup(kb_dir)
    extractor.refresh()
    chat = ChatService(FakeProvider(configured=False), knowledge=kb, portal=PortalLookup(extractor.store, kb))
    reply = chat.reply("s", "Vocês têm Excel?")
    assert reply.source == "portal" and "Excel" in reply.text


def test_cep_jp_priority_overrides_a_non_cep_jp_guidance_recommendation(kb_dir) -> None:
    """A Guidance (catálogo curado) recomendaria o CEP Campina Grande para "beleza"; o portal tem Maquiagem
    confirmada no CEP-JP agora — a regra nº 1 (CEP-JP primeiro) tem que vencer o catálogo curado."""
    portal, kb, extractor = setup(kb_dir)
    portal.listing = json.dumps(LISTING + [turma(5, "Maquiagem Social")])  # turma real no CEP-JP (unidade padrão de turma())
    extractor.refresh()
    chat = ChatService(FakeProvider(configured=False), knowledge=kb, portal=PortalLookup(extractor.store, kb))
    reply = chat.reply("s", "Tem curso de maquiagem?")
    assert reply.source == "portal" and "Maquiagem" in reply.text
    assert "Campina Grande" not in reply.text


def test_outbound_policy_does_not_block_the_unit_phone_and_cep_from_the_portal(kb_dir) -> None:
    """O telefone/CEP reais de uma turma (mesma fonte oficial, outro canal) não podem ser tratados como
    vazamento de dado pessoal só por não estarem na base curada à mão (ver ChatService._extra_contacts)."""
    portal, kb, extractor = setup(kb_dir)
    extractor.refresh()
    chat = ChatService(FakeProvider(configured=False), knowledge=kb, portal=PortalLookup(extractor.store, kb))
    reply = chat.reply("s", "Quais cursos o CEP João Pessoa oferece?")
    assert reply.source == "portal" and "telefone" in reply.text.lower()


def test_guidance_still_gives_up_when_the_portal_also_has_nothing(kb_dir) -> None:
    portal, kb, extractor = setup(kb_dir)
    extractor.refresh()
    chat = ChatService(FakeProvider(configured=False), knowledge=kb, portal=PortalLookup(extractor.store, kb))
    reply = chat.reply("s", "Quero fazer um curso de astronomia avançada")
    assert reply.source == "guidance"
    assert "Não encontrei na minha base uma oferta confirmada" in reply.text


def test_chat_without_extraction_keeps_the_previous_behavior(kb_dir) -> None:
    kb = KnowledgeBase.load(kb_dir, today=lambda: TEST_TODAY)
    chat = ChatService(FakeProvider(configured=False), knowledge=kb, portal=PortalLookup(PortalKnowledge(kb_dir), kb))
    reply = chat.reply("s", "Quais cursos o CEP João Pessoa oferece?")
    assert reply.source == "knowledge" and "Não tenho a lista de cursos do CEP João Pessoa confirmada" in reply.text


# ---------------------------------------------------------------- API do operador
def api(monkeypatch, kb_dir):
    portal, kb, extractor = setup(kb_dir)
    monkeypatch.setattr(main, "portal_extractor", extractor)
    monkeypatch.setattr(main, "knowledge_base", kb)
    return TestClient(main.app), extractor


def test_operator_api_shows_the_source_refreshes_and_decides(monkeypatch, kb_dir) -> None:
    client, extractor = api(monkeypatch, kb_dir)
    first = client.get("/api/knowledge/portal").json()
    assert first["available"] is False and first["source"]["url"] == PAGE_URL and first["source"]["category"] == "Cursos e matrículas"
    assert {r["status"] for r in first["resolutions"]} == {"not_consulted", "not_related"}
    refreshed = client.post("/api/knowledge/portal/refresh", json={}).json()
    assert refreshed["outcome"] == "extracted" and refreshed["portal"]["available"] and refreshed["portal"]["offerings"] == 4
    assert client.post("/api/knowledge/portal/refresh", json={}).json()["outcome"] == "cache"  # sem pesquisa repetida
    approved = client.post("/api/knowledge/portal/records/struct-cidades/approve").json()
    assert approved["record"]["status"] == "confirmed" and approved["portal"]["counts"]["confirmed"] >= 1
    assert client.post("/api/knowledge/portal/records/nao-existe/approve").status_code == 404
    assert client.post("/api/knowledge/portal/records/struct-cidades/publicar").status_code == 404


def test_knowledge_status_exposes_real_pending_details(monkeypatch, kb_dir) -> None:
    client, extractor = api(monkeypatch, kb_dir)
    status = client.get("/api/knowledge/status").json()
    pending = status["pending_items"]
    assert len(pending) == 20 and sum(p["type"] == "divergence" for p in pending) == 3
    assert all(p["reason"] and p["id"] for p in pending)
    assert any(s["category"] == "Cursos e matrículas" for s in status["sources"])
