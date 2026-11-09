"""Atualizador da base: robots.txt, domínios oficiais, validação, falhas e detecção de mudanças (sem usar a internet)."""
import json
import shutil
from pathlib import Path

import httpx
import pytest

from backend.knowledge import KnowledgeBase
from backend.knowledge.update import main as update_main
from backend.knowledge.updater import USER_AGENT, Updater, extract_text, fingerprint, validate_page
from backend.knowledge.models import Source
from tests.kb_helpers import KNOWLEDGE_DIR, TEST_TODAY

ROBOTS_OK = "User-agent: *\nDisallow: /wp-admin/\n"
GOOD_PAGE = "<html><head><title>Página X</title><script>var a=1;</script></head><body><h1>Gratuidade</h1><p>" + ("Texto institucional do Senac. " * 30) + "</p></body></html>"


class FakeSite:
    """Servidor simulado: guarda as páginas, registra as requisições e permite provocar falhas."""

    def __init__(self) -> None:
        self.pages: dict[str, tuple[int, str, dict]] = {}
        self.requests: list[str] = []
        self.robots: tuple[int, str] = (200, ROBOTS_OK)

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.requests.append(url)
        assert request.headers["user-agent"] == USER_AGENT
        if url.endswith("/robots.txt"):
            return httpx.Response(self.robots[0], text=self.robots[1])
        status, body, headers = self.pages.get(url, (404, "", {}))
        return httpx.Response(status, text=body, headers={"content-type": "text/html", **headers})


def make_dir(tmp_path: Path, sources: list[dict], allowed=("senac.br",)) -> Path:
    directory = tmp_path / "kb"
    directory.mkdir(parents=True)
    (directory / "sources.json").write_text(json.dumps({
        "version": 1, "allowed_domains": list(allowed),
        "freshness_days": {"permanent": 365, "periodic": 120, "volatile": 30}, "sources": sources,
    }), encoding="utf-8")
    return directory


def source(id_: str, url: str, **extra) -> dict:
    base = {"id": id_, "name": id_, "url": url, "level": "paraiba", "freshness": "periodic",
            "dynamic": False, "expect": ["Gratuidade"], "min_length": 200}
    base.update(extra)
    return base


def updater(directory: Path, site: FakeSite, sleeps: list[float] | None = None) -> Updater:
    client = httpx.Client(transport=httpx.MockTransport(site.handler), headers={"User-Agent": USER_AGENT})
    return Updater(directory, client=client, sleep=(sleeps.append if sleeps is not None else (lambda _: None)),
                   delay=2.5, now=lambda: "2026-11-07T12:00:00+00:00")


def state(directory: Path) -> dict:
    return json.loads((directory / "state.json").read_text(encoding="utf-8"))["sources"]


def test_extract_text_ignores_scripts_and_styles() -> None:
    title, text = extract_text("<html><head><title> Olá  Senac </title><style>x{}</style></head><body><script>alert(1)</script><p>Texto  visível</p></body></html>")
    assert title == "Olá Senac" and text == "Texto visível"


def test_fingerprint_ignores_spacing_and_accents_but_not_content() -> None:
    assert fingerprint("Olá   mundo") == fingerprint("ola mundo")
    assert fingerprint("Olá mundo") != fingerprint("Olá mundo!!x")


def test_validate_page_rules() -> None:
    src = Source("x", "x", "https://pb.senac.br/", "paraiba", "periodic", expect=("Gratuidade",), min_length=50)
    assert validate_page(src, "curto") is not None
    assert "marcador" in validate_page(src, "Texto longo " * 20)
    assert validate_page(src, "Programa de Gratuidade " * 10) is None


def test_first_run_records_baseline_snapshot_and_state(tmp_path) -> None:
    directory = make_dir(tmp_path, [source("a", "https://pb.senac.br/a/")])
    site = FakeSite()
    site.pages["https://pb.senac.br/a/"] = (200, GOOD_PAGE, {})
    results = updater(directory, site).run()
    assert [r.outcome for r in results] == ["new"]
    snap = json.loads((directory / "snapshots" / "a.json").read_text(encoding="utf-8"))
    assert snap["sha256"] and snap["title"] == "Página X" and len(snap["excerpt"]) <= 1500
    info = state(directory)["a"]
    assert info["hash"] == info["reviewed_hash"] and info["needs_review"] is False
    assert info["last_ok"] and info["consecutive_failures"] == 0 and info["error"] is None


def test_requests_are_spaced_and_use_the_identified_user_agent(tmp_path) -> None:
    directory = make_dir(tmp_path, [source("a", "https://pb.senac.br/a/"), source("b", "https://pb.senac.br/b/")])
    site = FakeSite()
    site.pages["https://pb.senac.br/a/"] = (200, GOOD_PAGE, {})
    site.pages["https://pb.senac.br/b/"] = (200, GOOD_PAGE, {})
    sleeps: list[float] = []
    updater(directory, site, sleeps).run()
    assert site.requests.count("https://pb.senac.br/robots.txt") == 1  # robots.txt consultado uma vez por site
    assert len(sleeps) == len(site.requests) - 1 and all(s >= 2.5 for s in sleeps)


def test_unchanged_page_keeps_state_and_changed_page_requires_review(tmp_path) -> None:
    directory = make_dir(tmp_path, [source("a", "https://pb.senac.br/a/")])
    site = FakeSite()
    url = "https://pb.senac.br/a/"
    site.pages[url] = (200, GOOD_PAGE, {})
    updater(directory, site).run()
    assert updater(directory, site).run()[0].outcome == "unchanged"
    site.pages[url] = (200, GOOD_PAGE.replace("Texto institucional", "Texto NOVO institucional"), {})
    result = updater(directory, site).run()[0]
    assert result.outcome == "changed" and "revisão" in result.detail
    info = state(directory)["a"]
    assert info["needs_review"] is True and info["changed_at"] and info["hash"] != info["reviewed_hash"]
    assert updater(directory, site).run()[0].outcome == "unchanged"
    assert state(directory)["a"]["needs_review"] is True  # continua pendente até a revisão humana


def test_acknowledge_clears_the_review_flag(tmp_path) -> None:
    directory = make_dir(tmp_path, [source("a", "https://pb.senac.br/a/")])
    site = FakeSite()
    url = "https://pb.senac.br/a/"
    site.pages[url] = (200, GOOD_PAGE, {})
    updater(directory, site).run()
    site.pages[url] = (200, GOOD_PAGE + "<p>Mudou</p>", {})
    updater(directory, site).run()
    assert state(directory)["a"]["needs_review"] is True
    assert updater(directory, site).acknowledge(["a", "inexistente"]) == ["a"]
    assert state(directory)["a"]["needs_review"] is False


def test_noisy_sources_do_not_require_review_when_they_change(tmp_path) -> None:
    directory = make_dir(tmp_path, [source("home", "https://pb.senac.br/", noisy=True)])
    site = FakeSite()
    site.pages["https://pb.senac.br/"] = (200, GOOD_PAGE, {})
    updater(directory, site).run()
    site.pages["https://pb.senac.br/"] = (200, GOOD_PAGE + "<p>Nova notícia</p>", {})
    assert updater(directory, site).run()[0].outcome == "changed"
    assert state(directory)["home"]["needs_review"] is False


def test_robots_disallow_blocks_the_request(tmp_path) -> None:
    directory = make_dir(tmp_path, [source("a", "https://pb.senac.br/privado/x")])
    site = FakeSite()
    site.robots = (200, "User-agent: *\nDisallow: /privado/\n")
    site.pages["https://pb.senac.br/privado/x"] = (200, GOOD_PAGE, {})
    result = updater(directory, site).run()[0]
    assert result.outcome == "failed" and "robots.txt" in result.detail
    assert "https://pb.senac.br/privado/x" not in site.requests


def test_robots_forbidden_or_server_error_means_do_not_fetch(tmp_path) -> None:
    for status, text in ((403, ""), (503, "")):
        directory = make_dir(tmp_path / str(status), [source("a", "https://pb.senac.br/a/")])
        site = FakeSite()
        site.robots = (status, text)
        site.pages["https://pb.senac.br/a/"] = (200, GOOD_PAGE, {})
        result = updater(directory, site).run()[0]
        assert result.outcome == "failed"
        assert "https://pb.senac.br/a/" not in site.requests


def test_missing_robots_txt_allows_access(tmp_path) -> None:
    directory = make_dir(tmp_path, [source("a", "https://pb.senac.br/a/")])
    site = FakeSite()
    site.robots = (404, "")
    site.pages["https://pb.senac.br/a/"] = (200, GOOD_PAGE, {})
    assert updater(directory, site).run()[0].outcome == "new"


def test_failure_preserves_the_last_valid_version(tmp_path) -> None:
    directory = make_dir(tmp_path, [source("a", "https://pb.senac.br/a/")])
    site = FakeSite()
    url = "https://pb.senac.br/a/"
    site.pages[url] = (200, GOOD_PAGE, {})
    updater(directory, site).run()
    good = json.loads((directory / "snapshots" / "a.json").read_text(encoding="utf-8"))
    before = state(directory)["a"]
    for failing in ((500, "erro", {}), (200, "<p>Página não encontrada</p>", {})):
        site.pages[url] = failing
        result = updater(directory, site).run()[0]
        assert result.outcome == "failed"
    after = state(directory)["a"]
    assert after["hash"] == before["hash"] and after["last_ok"] == before["last_ok"]
    assert after["consecutive_failures"] == 2 and after["error"]
    assert json.loads((directory / "snapshots" / "a.json").read_text(encoding="utf-8")) == good


def test_validation_failure_never_overwrites_the_snapshot(tmp_path) -> None:
    directory = make_dir(tmp_path, [source("a", "https://pb.senac.br/a/")])
    site = FakeSite()
    url = "https://pb.senac.br/a/"
    site.pages[url] = (200, GOOD_PAGE, {})
    updater(directory, site).run()
    good = (directory / "snapshots" / "a.json").read_text(encoding="utf-8")
    site.pages[url] = (200, "<html><body>" + "Texto sem o marcador. " * 40 + "</body></html>", {})
    result = updater(directory, site).run()[0]
    assert result.outcome == "failed" and "validação falhou" in result.detail
    assert (directory / "snapshots" / "a.json").read_text(encoding="utf-8") == good


def test_network_errors_do_not_crash_the_run(tmp_path) -> None:
    directory = make_dir(tmp_path, [source("a", "https://pb.senac.br/a/"), source("b", "https://pb.senac.br/b/")])

    def boom(request):
        if str(request.url).endswith("/robots.txt"):
            return httpx.Response(200, text=ROBOTS_OK)
        raise httpx.ConnectError("sem internet")

    client = httpx.Client(transport=httpx.MockTransport(boom))
    results = Updater(directory, client=client, sleep=lambda _: None).run()
    assert [r.outcome for r in results] == ["failed", "failed"]
    assert all("rede" in r.detail for r in results)


def test_only_official_domains_are_accepted(tmp_path) -> None:
    directory = make_dir(tmp_path, [source("a", "https://blog.exemplo.com/senac")])
    with pytest.raises(ValueError, match="oficiais"):
        updater(directory, FakeSite()).run()
    directory = make_dir(tmp_path / "http", [source("a", "http://pb.senac.br/a/")])
    with pytest.raises(ValueError):
        updater(directory, FakeSite()).run()


def test_redirect_to_unofficial_domain_is_refused(tmp_path) -> None:
    directory = make_dir(tmp_path, [source("a", "https://pb.senac.br/a/")])
    site = FakeSite()
    site.pages["https://pb.senac.br/a/"] = (302, "", {"location": "https://evil.example.com/senac"})
    result = updater(directory, site).run()[0]
    assert result.outcome == "failed" and "fora dos domínios oficiais" in result.detail
    assert not any("evil.example.com" in r for r in site.requests)


def test_redirect_within_official_domain_is_followed(tmp_path) -> None:
    directory = make_dir(tmp_path, [source("a", "https://pb.senac.br/a/")])
    site = FakeSite()
    site.pages["https://pb.senac.br/a/"] = (301, "", {"location": "/novo/"})
    site.pages["https://pb.senac.br/novo/"] = (200, GOOD_PAGE, {})
    assert updater(directory, site).run()[0].outcome == "new"


def test_dynamic_source_only_checks_reachability(tmp_path) -> None:
    directory = make_dir(tmp_path, [source("din", "https://pb.senac.br/programacao/", dynamic=True, expect=[], min_length=0)])
    site = FakeSite()
    site.pages["https://pb.senac.br/programacao/"] = (200, "<html><body>Carregando...</body></html>", {})
    result = updater(directory, site).run()[0]
    assert result.outcome == "dynamic" and "JavaScript" in result.detail
    assert "hash" not in state(directory)["din"] and not (directory / "snapshots").exists()


def test_dry_run_does_not_write_state(tmp_path) -> None:
    directory = make_dir(tmp_path, [source("a", "https://pb.senac.br/a/")])
    site = FakeSite()
    site.pages["https://pb.senac.br/a/"] = (200, GOOD_PAGE, {})
    updater(directory, site).run(dry_run=True)
    assert not (directory / "state.json").exists()


def test_only_filter_limits_the_requested_sources(tmp_path) -> None:
    directory = make_dir(tmp_path, [source("a", "https://pb.senac.br/a/"), source("b", "https://pb.senac.br/b/")])
    site = FakeSite()
    site.pages["https://pb.senac.br/a/"] = (200, GOOD_PAGE, {})
    results = updater(directory, site).run(only=["a"])
    assert [r.id for r in results] == ["a"]
    assert "https://pb.senac.br/b/" not in site.requests


# ---------- integração com a base ----------

def test_changed_source_downgrades_linked_entries_to_review(tmp_path) -> None:
    kb_dir = tmp_path / "kb"
    shutil.copytree(KNOWLEDGE_DIR, kb_dir, ignore=shutil.ignore_patterns("snapshots", "state.json"))
    clean = KnowledgeBase.load(kb_dir, today=lambda: TEST_TODAY)
    assert clean.effective(clean.get("pb-historia")) == "verified"
    (kb_dir / "state.json").write_text(json.dumps({"sources": {"pb-quem-somos": {"needs_review": True, "consecutive_failures": 0}}}), encoding="utf-8")
    flagged = KnowledgeBase.load(kb_dir, today=lambda: TEST_TODAY)
    assert flagged.effective(flagged.get("pb-historia")) == "review"
    assert flagged.summary()["sources_review"] == 1
    answer = flagged.answer_for(flagged.search("Qual a história do Senac Paraíba?"))
    assert "precisa de confirmação" in answer


def test_cli_report_runs_on_the_real_base(capsys) -> None:
    assert update_main(["--report"]) == 0
    out = capsys.readouterr().out
    assert "Base de conhecimento:" in out and "Pendências registradas" in out and "Fontes:" in out
