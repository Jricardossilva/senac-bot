"""Atualização da base de conhecimento a partir das fontes oficiais.

O que o atualizador FAZ (de forma conservadora e verificável):
 - consulta somente as páginas do registro knowledge/sources.json (domínios oficiais do Senac, HTTPS);
 - respeita o robots.txt de cada site, identifica-se com um User-Agent próprio, espaça as requisições e
   nunca acessa áreas autenticadas;
 - valida o que baixou (tamanho mínimo e marcadores esperados) antes de aceitar;
 - calcula uma impressão digital do texto e detecta MUDANÇAS na página oficial;
 - preserva sempre a última versão válida (snapshots/) quando uma consulta falha ou não valida;
 - registra datas, falhas e o que precisa de revisão em knowledge/state.json.

O que NÃO faz: reescrever o conteúdo curado (JSON). Páginas oficiais mudam de formato e de texto; extrair fatos
automaticamente sem revisão arriscaria publicar um dado errado. Quando uma fonte muda, as entradas ligadas a
ela passam a "a confirmar" e o assistente avisa; depois da revisão humana, `--ack` confirma o novo estado.
"""
import hashlib
import json
import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

import httpx

from backend.knowledge.fetch import MAX_REDIRECTS, TIMEOUT_SECONDS, PoliteFetcher  # noqa: F401

from backend.knowledge.models import LoadReport, Source
from backend.knowledge.store import is_official_url, load_json, load_source_state, load_sources
from backend.knowledge.text import normalize

logger = logging.getLogger("senac_bot.knowledge.updater")

USER_AGENT = "SENAC-BOT-KnowledgeUpdater/1.0 (projeto educacional Robotica 2026; leitura de paginas publicas)"  # ASCII: cabecalho HTTP
DEFAULT_DELAY_SECONDS = 2.5
MAX_BYTES = 3_000_000  # páginas maiores não são lidas
SNAPSHOT_TEXT_LIMIT = 250_000  # texto guardado no snapshot (permite conferir os fatos offline)


class _TextExtractor(HTMLParser):
    _SKIP = {"script", "style", "noscript", "template", "svg", "head"}

    def __init__(self) -> None:
        super().__init__()
        self.title = ""
        self._parts: list[str] = []
        self._skip_depth = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._in_title = True
        elif tag in self._SKIP:
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip_depth and data.strip():
            self._parts.append(data.strip())

    @property
    def text(self) -> str:
        return " ".join(self._parts)


def extract_text(html: str) -> tuple[str, str]:
    """(título, texto visível) de uma página HTML; ignora scripts e estilos."""
    parser = _TextExtractor()
    parser.feed(html)
    return " ".join(parser.title.split()), " ".join(parser.text.split())


def fingerprint(text: str) -> str:
    return hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()


def validate_page(source: Source, text: str) -> str | None:
    """Motivo da rejeição, ou None se a página é aceitável."""
    if len(text) < source.min_length:
        return f"texto muito curto ({len(text)} < {source.min_length} caracteres): possível página de erro"
    normalized = normalize(text)
    for marker in source.expect:
        if normalize(marker) not in normalized:
            return f"marcador esperado ausente: {marker!r}"
    return None


@dataclass
class SourceResult:
    id: str
    outcome: str  # new | unchanged | changed | dynamic | failed | skipped
    detail: str = ""
    http_status: int | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


class Updater:
    def __init__(
        self,
        directory: Path,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        delay: float = DEFAULT_DELAY_SECONDS,
        now: Callable[[], str] = _now,
    ) -> None:
        self.directory = directory
        self._fetcher = PoliteFetcher(USER_AGENT, client, sleep, delay)
        self._now = now

    # ---------- rede com educação (compartilhada com o Gerenciador de Eventos) ----------
    def _fetch_page(self, source: Source, allowed_domains: list[str]) -> tuple[httpx.Response | None, str]:
        return self._fetcher.fetch(
            source.url, lambda url: is_official_url(url, allowed_domains), "endereço fora dos domínios oficiais"
        )

    # ---------- execução ----------
    def run(self, only: list[str] | None = None, dry_run: bool = False) -> list[SourceResult]:
        report = LoadReport()
        sources, allowed, _ = load_sources(self.directory, report)
        if report.errors:
            raise ValueError("sources.json inválido: " + "; ".join(report.errors))
        state = load_source_state(self.directory)
        results: list[SourceResult] = []
        for source in sources.values():
            if only and source.id not in only:
                continue
            result = self._update_one(source, allowed, state)
            results.append(result)
            logger.info("%s: %s %s", source.id, result.outcome, result.detail)
        if not dry_run:
            _atomic_write(self.directory / "state.json", {"updated_at": self._now(), "sources": state})
        return results

    def _update_one(self, source: Source, allowed: list[str], state: dict[str, dict]) -> SourceResult:
        entry = state.setdefault(source.id, {})
        entry.update({"url": source.url, "last_checked": self._now()})

        def fail(reason: str, status: int | None = None) -> SourceResult:
            entry["error"] = reason
            entry["http_status"] = status
            entry["consecutive_failures"] = int(entry.get("consecutive_failures", 0)) + 1
            return SourceResult(source.id, "failed", reason, status)  # a última versão válida é preservada

        response, problem = self._fetch_page(source, allowed)
        if response is None:
            return fail(problem)
        if response.status_code != 200:
            return fail(f"HTTP {response.status_code}", response.status_code)
        if "html" not in response.headers.get("content-type", "html").lower():
            return fail("conteúdo não é HTML", response.status_code)
        if len(response.content) > MAX_BYTES:
            return fail("página grande demais", response.status_code)

        title, text = extract_text(response.text)
        if source.dynamic:
            entry.update({"http_status": 200, "last_ok": self._now(), "error": None, "consecutive_failures": 0,
                          "title": title, "needs_review": False})
            return SourceResult(source.id, "dynamic", "conteúdo carregado por JavaScript: não verificável automaticamente", 200)

        rejection = validate_page(source, text)
        if rejection:
            return fail(f"validação falhou: {rejection}", 200)  # last_ok e snapshot anteriores são preservados

        entry.update({"http_status": 200, "last_ok": self._now(), "error": None, "consecutive_failures": 0, "title": title})
        digest = fingerprint(text)
        previous = entry.get("hash")
        entry.update({"hash": digest, "length": len(text)})
        self._write_snapshot(source, title, text, digest)
        if previous is None:
            entry["reviewed_hash"] = digest  # linha de base: o conteúdo curado foi extraído desta versão
            entry["needs_review"] = False
            return SourceResult(source.id, "new", "linha de base registrada", 200)
        if previous == digest:
            entry["needs_review"] = bool(not source.noisy and digest != entry.get("reviewed_hash"))
            return SourceResult(source.id, "unchanged", "", 200)
        entry["changed_at"] = self._now()
        entry["needs_review"] = bool(not source.noisy and digest != entry.get("reviewed_hash"))
        detail = "página oficial mudou; entradas ligadas ficam 'a confirmar' até a revisão" if entry["needs_review"] else "página oficial mudou (fonte dinâmica por natureza)"
        return SourceResult(source.id, "changed", detail, 200)

    def _write_snapshot(self, source: Source, title: str, text: str, digest: str) -> None:
        _atomic_write(
            self.directory / "snapshots" / f"{source.id}.json",
            {"id": source.id, "url": source.url, "fetched_at": self._now(), "sha256": digest, "length": len(text),
             "title": title, "excerpt": text[:1500], "text": text[:SNAPSHOT_TEXT_LIMIT]},
        )

    def acknowledge(self, source_ids: list[str]) -> list[str]:
        """Revisão humana concluída: o conteúdo atual da fonte passa a ser a referência."""
        state = load_source_state(self.directory)
        done = []
        for source_id in source_ids:
            entry = state.get(source_id)
            if entry and entry.get("hash"):
                entry["reviewed_hash"] = entry["hash"]
                entry["needs_review"] = False
                done.append(source_id)
        _atomic_write(self.directory / "state.json", {"updated_at": self._now(), "sources": state})
        return done


def read_pending(directory: Path) -> list[dict]:
    try:
        return load_json(directory / "pending.json").get("items", [])
    except (OSError, ValueError):
        return []
