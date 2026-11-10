"""Portal oficial de matrículas do Senac PB (Cursos Técnicos — Senac Paraíba): consulta, extração e rastreabilidade.

Fonte: https://pb.senac.br/matriculas/matricula/cursos-tecnicos/index.php (fonte oficial; categoria "Cursos e matrículas").
A página monta a lista de turmas por JavaScript, chamando a própria listagem pública do portal (get-turmas.php, a mesma
chamada que o navegador faz ao abrir a página). Esta extração:
 - respeita o robots.txt, espaça as requisições e identifica-se (PoliteFetcher), só em domínio oficial HTTPS;
 - copia SOMENTE campos de uma lista permitida. Qualquer campo de credencial/pagamento que o endpoint devolva é descartado
   e nunca é gravado ou exibido (a resposta é processada em memória);
 - nunca aprova nada sozinha: tudo nasce "Encontrada" ou "Aguardando validação"; só o operador confirma;
 - se uma informação já aprovada mudar, a versão antiga continua valendo e a nova vira proposta;
 - guarda URL, data da consulta, situação e data da próxima revisão de cada registro; em falha, mantém a última versão;
 - relaciona cada registro às pendências de knowledge/pending.json, sem apagá-las.
Valores e vagas mudam o tempo todo: o robô os fala SEMPRE com a data da consulta e a ressalva de que mudam.
A consulta é feita antes (todo dia, na inicialização e em segundo plano): o chat nunca espera a rede.
"""
import copy
import json
import logging
import os
import re
import urllib.parse
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

from backend.knowledge.fetch import PoliteFetcher
from backend.knowledge.store import is_official_url, load_json
from backend.knowledge.text import normalize, tokenize

logger = logging.getLogger("senac_bot.knowledge.portal")

SOURCE_ID = "pb-programacao-cursos"
CATEGORY = "Cursos e matrículas"
LISTING_FILE = "get-turmas.php"
EXTRACTION_PATH = Path("extractions") / f"{SOURCE_ID}.json"
REVIEW_DAYS = 7  # a lista de turmas muda rápido: nova revisão semanal
MIN_REFRESH_GAP = timedelta(minutes=10)  # nunca consulta de novo em sequência
MAX_CONTENT_WORDS = 90
MAX_COURSES_PER_UNIT = 3  # nomes de curso citados por unidade numa resposta do PortalLookup
HISTORY_LIMIT = 30
STATUSES = ("found", "confirmed", "awaiting_validation", "divergent", "stale", "rejected")
STATUS_LABELS = {
    "found": "Encontrada", "confirmed": "Confirmada", "awaiting_validation": "Aguardando validação",
    "divergent": "Divergente", "stale": "Desatualizada", "rejected": "Rejeitada",
}
RESOLUTION_LABELS = {
    "resolved": "Resolvida (confirmada pelo operador)", "awaiting_validation": "Informação encontrada, aguardando validação",
    "divergent": "Informação divergente", "unresolved": "Continua sem solução", "failed": "Consulta falhou: pendência mantida",
    "not_related": "Não relacionada a esta fonte", "not_consulted": "Fonte ainda não consultada",
}

# Campos copiados da listagem (tudo o mais, inclusive qualquer campo de credencial, é descartado)
KEEP_FIELDS = (
    "CODI_TURMA", "CODI_CURSO", "NOME_CURSO", "DATA_INICIO", "DATA_FIM", "DIAS_DA_SEMANA", "HORARIO", "CARGA_HORARIA",
    "NOME_MUNICIPIO", "NOME_UOPER", "NOME_FANTASIA_UOPER", "ENDERECO_UOPER", "NUMERO_UOPER", "BAIRRO_UOPER", "CEP_UOPER",
    "TELEFONE_UOPER", "DESC_NIVEL", "NOME_NATU", "NOME_AREA", "SEGMENTO", "DESCRICAO_ESCOLARIDADE", "FAIXA_ETARIA",
    "VALORCURSO", "VALOR_MATRICULA", "VALOR_PARCELADO", "NUMEROPARCELAS", "VAGASDISPONIVEIS",
)
VOLATILE_FIELDS = ("VALORCURSO", "VALOR_MATRICULA", "VALOR_PARCELADO", "NUMEROPARCELAS", "VAGASDISPONIVEIS")
SENSITIVE = re.compile(r"token|chave|key|merchant|secret|senha|password|^pv_|api_|convenio", re.IGNORECASE)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _atomic_write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


ACRONYMS = {"cep": "CEP", "cendege": "CENDEGE", "ead": "EAD", "uf": "UF", "joao": "João", "jose": "José", "antonio": "Antônio"}


def _title(text: str) -> str:
    small = {"de", "da", "do", "das", "dos", "e", "em", "a", "o"}
    words = str(text).strip().lower().split()
    return " ".join(ACRONYMS.get(w, w if (i and w in small) else w.capitalize()) for i, w in enumerate(words))


def _clip(text: str) -> str:
    words = text.split()
    return text if len(words) <= MAX_CONTENT_WORDS else " ".join(words[:MAX_CONTENT_WORDS]).rstrip(",;") + "…"


def _br(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%d/%m/%Y")
    except ValueError:
        return iso


def _format_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", str(raw or ""))
    if len(digits) == 11:
        return f"({digits[:2]}) {digits[2:7]}-{digits[7:]}"
    if len(digits) == 10:
        return f"({digits[:2]}) {digits[2:6]}-{digits[6:]}"
    return str(raw or "")


def _format_cep(raw: str) -> str:
    digits = re.sub(r"\D", "", str(raw or ""))
    return f"{digits[:5]}-{digits[5:]}" if len(digits) == 8 else str(raw or "")


def _address_text(endereco: dict) -> str:
    """Local e contato da unidade, a partir dos mesmos campos permitidos da listagem (nada é inventado)."""
    street = str(endereco.get("logradouro") or "")
    numero = endereco.get("numero")
    if street and numero:
        street = f"{street}, {numero}"
    for extra in (str(endereco.get("bairro") or ""), _format_cep(endereco.get("cep"))):
        if extra:
            street = f"{street}, {extra}" if street else extra
    telefone = _format_phone(endereco.get("telefone"))
    if telefone:
        street = f"{street}, telefone {telefone}" if street else f"telefone {telefone}"
    return street


# ------------------------------------------------------------------------------------------------ leitura da página
def parse_structure(html: str) -> dict[str, list[str]]:
    """Listas literais que a página oferece nos filtros (cidades, unidades, segmentos, modalidades, tipos de formação, turnos)."""
    def options(select_id: str) -> list[str]:
        match = re.search(rf"<select[^>]*id=['\"]{select_id}['\"][^>]*>(.*?)</select>", html, re.S)
        found = [re.sub(r"\s+", " ", o).strip() for o in re.findall(r"<option[^>]*>(.*?)</option>", match.group(1), re.S)] if match else []
        return [o for o in found if o and not o.lower().startswith("todas") and not o.lower().startswith("todos")]

    def labels(css_class: str) -> list[str]:
        found = re.findall(rf"<label[^>]*>\s*<input[^>]*class=['\"]{css_class}['\"][^>]*>\s*([^<]+?)\s*</label>", html, re.S)
        return [re.sub(r"\s+", " ", x).strip() for x in found]

    return {
        "cidades": options("filtro-cidade"), "unidades": options("filtro-unidade"), "segmentos": options("filtro-area"),
        "modalidades": labels("filtro-nivel"), "tipos_formacao": labels("filtro-tpformacao"), "turnos": labels("filtro-turno"),
        "tem_carrinho": ["carrinho"] if re.search(r"Ver Carrinho", html) else [],
    }


def parse_listing(text: str) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    """(turmas, nomes dos campos vistos, nomes de campos sensíveis descartados). Só os campos permitidos são copiados."""
    data = json.loads(text)
    if not isinstance(data, list):
        raise ValueError("a listagem não devolveu uma lista")
    seen: set[str] = set()
    dropped: set[str] = set()
    turmas: list[dict[str, Any]] = []
    for row in data:
        if not isinstance(row, dict):
            continue
        seen.update(row)
        dropped.update(k for k in row if SENSITIVE.search(k))
        turmas.append({k: row.get(k) for k in KEEP_FIELDS if k in row})
    return turmas, sorted(seen), sorted(dropped)


def normalize_offering(row: dict[str, Any], unit_of: Callable[[str], str | None]) -> dict[str, Any]:
    unit_name = _title(row.get("NOME_FANTASIA_UOPER") or row.get("NOME_UOPER") or "")
    offering = {
        "id": int(row["CODI_TURMA"]) if str(row.get("CODI_TURMA", "")).isdigit() else row.get("CODI_TURMA"),
        "curso": _title(row.get("NOME_CURSO") or ""), "unidade": unit_name, "unidade_chave": unit_of(f"{row.get('NOME_FANTASIA_UOPER') or ''} {row.get('NOME_UOPER') or ''}"),
        "cidade": _title(row.get("NOME_MUNICIPIO") or ""), "inicio": (row.get("DATA_INICIO") or "")[:10], "fim": (row.get("DATA_FIM") or "")[:10],
        "dias": _title(row.get("DIAS_DA_SEMANA") or ""), "horario": row.get("HORARIO") or "", "carga_horaria": row.get("CARGA_HORARIA"),
        "modalidade": row.get("DESC_NIVEL") or "", "natureza": row.get("NOME_NATU") or "", "area": row.get("NOME_AREA") or "",
        "segmento": row.get("SEGMENTO") or "", "escolaridade": row.get("DESCRICAO_ESCOLARIDADE") or "", "idade_minima": row.get("FAIXA_ETARIA"),
        "endereco": {"logradouro": _title(row.get("ENDERECO_UOPER") or ""), "numero": row.get("NUMERO_UOPER"), "bairro": _title(row.get("BAIRRO_UOPER") or ""),
                     "cep": row.get("CEP_UOPER") or "", "telefone": row.get("TELEFONE_UOPER") or ""},
        "volatil": {k: row.get(k) for k in VOLATILE_FIELDS if k in row},
    }
    return offering


# ------------------------------------------------------------------------------------------------ registros
@dataclass
class Resolution:
    pending_id: str
    topic: str
    status: str
    note: str
    record_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"pending_id": self.pending_id, "topic": self.topic, "status": self.status, "label": RESOLUTION_LABELS[self.status],
                "note": self.note, "record_ids": self.record_ids}


def _record(rid: str, kind: str, title: str, content: str, stamp: str, next_review: str, status: str, **extra: Any) -> dict[str, Any]:
    base = {"id": rid, "kind": kind, "title": title, "content": _clip(content), "category": CATEGORY, "source_id": SOURCE_ID,
            "consulted_at": stamp, "next_review": next_review, "status": status, "pending_ids": [], "approved_by": None, "approved_at": None,
            "volatile": False, "speakable": True, "unit": None, "note": "", "update_proposal": None}
    base.update(extra)
    return base


def _join(items: list[str], limit: int = 8) -> str:
    items = list(dict.fromkeys(items))
    shown = items[:limit]
    text = ", ".join(shown[:-1]) + (" e " if len(shown) > 1 else "") + shown[-1] if shown else ""
    return text + (f" e mais {len(items) - limit}" if len(items) > limit else "")


PORTAL_KEY = "_portal/pb-programacao-cursos.json"  # chave no banco; "_portal" nunca é um evento (não aparece na lista de eventos)


class PortalStorageError(RuntimeError):
    """A decisão/extração não pôde ser gravada no banco. A mensagem é segura para o operador (sem host, usuário ou senha)."""


class PortalStorage(Protocol):
    """O mesmo armazenamento dos eventos (MySQLStorage): documentos JSON por chave."""

    def read(self, key: str) -> Any | None: ...
    def write(self, key: str, data: Any) -> None: ...


class PortalKnowledge:
    """Extração do portal (turmas, registros, decisões do operador e pendências).

    Com `storage` (MySQL), a extração vive no banco e SOBREVIVE a reinícios e deploys do Render (disco efêmero). O arquivo
    knowledge/extractions/pb-programacao-cursos.json, versionado no Git, é só a SEMENTE: usado enquanto o banco está vazio
    ou fora do ar. Sem `storage` (desenvolvimento local), o arquivo é a fonte única, como sempre foi.
    """

    def __init__(self, directory: Path, today: Callable[[], date] = date.today, now: Callable[[], str] = _now,
                 storage: PortalStorage | None = None) -> None:
        self.directory = Path(directory)
        self.path = self.directory / EXTRACTION_PATH
        self._today = today
        self._now = now
        self._storage = storage

    @property
    def storage_kind(self) -> str:
        return "mysql" if self._storage is not None else "arquivo"

    # ---------------------------------------------------------------- leitura e gravação
    def _load_file(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def load(self) -> dict[str, Any]:
        if self._storage is not None:
            try:
                data = self._storage.read(PORTAL_KEY)
            except Exception as error:  # noqa: BLE001 - banco fora do ar: o chat segue com a semente versionada
                logger.warning("Extração do portal: banco indisponível na leitura (%s); usando o arquivo versionado.", type(error).__name__)
            else:
                if isinstance(data, dict) and data:
                    return copy.deepcopy(data)  # o cache do armazenamento nunca é alterado por quem chama
        return self._load_file()

    def save(self, data: dict[str, Any]) -> bool:
        """Grava a extração. True = gravou no armazenamento configurado (banco ou, sem banco, arquivo).
        False = o banco falhou: a extração foi gravada no arquivo só para valer nesta execução (o chat continua com dado novo)."""
        if self._storage is not None:
            try:
                self._storage.write(PORTAL_KEY, data)
                return True
            except Exception as error:  # noqa: BLE001
                logger.error("Extração do portal: banco indisponível na gravação (%s); gravada só em arquivo (não persistente no Render).",
                             type(error).__name__)
                _atomic_write(self.path, data)
                return False
        _atomic_write(self.path, data)
        return True

    @property
    def available(self) -> bool:
        return bool(self.load().get("consulted_at"))

    def is_due(self) -> bool:
        data = self.load()
        review = data.get("next_review")
        return not review or date.fromisoformat(review[:10]) <= self._today()

    def offerings(self) -> list[dict[str, Any]]:
        return list(self.load().get("offerings", []))

    # ---------------------------------------------------------------- decisões do operador
    def decide(self, record_id: str, decision: str) -> dict[str, Any]:
        data = self.load()
        record = next((r for r in data.get("records", []) if r["id"] == record_id), None)
        if record is None:
            raise KeyError(record_id)
        stamp = self._now()
        if decision == "approve":
            if record.get("update_proposal"):  # aceitar a versão nova de um registro já aprovado
                record["content"] = record["update_proposal"]["content"]
                record["consulted_at"] = record["update_proposal"]["consulted_at"]
                record["update_proposal"] = None
            record.update(status="confirmed", approved_by="operator", approved_at=stamp)
        elif decision == "reject":
            record.update(status="rejected", approved_by=None, approved_at=None, update_proposal=None)
        else:
            raise ValueError(decision)
        data["resolutions"] = [r.to_dict() for r in self.resolve(data)]
        data.setdefault("history", []).append({"at": stamp, "kind": "decisao", "summary": f"{record['title']}: {decision}"})
        data["history"] = data["history"][-HISTORY_LIMIT:]
        if not self.save(data):
            raise PortalStorageError("Banco de dados indisponível: a decisão vale só até o robô reiniciar.")
        return record

    # ---------------------------------------------------------------- pendências
    def resolve(self, data: dict[str, Any], pending_items: list[dict] | None = None) -> list[Resolution]:
        pending_items = pending_items if pending_items is not None else self._pending()
        records = {r["id"]: r for r in data.get("records", [])}
        failed = bool(data.get("error")) and not records
        never = not data.get("consulted_at") and not data.get("error")
        out: list[Resolution] = []
        for pend in pending_items:
            rule = RESOLUTION_RULES.get(pend.get("id", ""))
            topic = pend.get("topic", "")
            if rule is None:
                out.append(Resolution(pend["id"], topic, "not_related", "Esta pendência não depende da página de cursos técnicos."))
                continue
            record_ids = [rid for rid in rule["records"](records) if rid in records]
            if never:
                out.append(Resolution(pend["id"], topic, "not_consulted", "Use CONSULTAR FONTE para pesquisar esta informação na página oficial."))
            elif failed:
                out.append(Resolution(pend["id"], topic, "failed", "A consulta à fonte falhou; a pendência foi mantida sem alteração."))
            elif not record_ids:
                out.append(Resolution(pend["id"], topic, "unresolved", rule["absent"]))
            else:
                linked = [records[r] for r in record_ids]
                live = [r for r in linked if r["status"] != "rejected"]
                if not live:
                    status, note = "unresolved", "Os registros encontrados foram rejeitados pelo operador."
                elif any(r["status"] == "divergent" for r in live):
                    status, note = "divergent", rule["found"] + " Há divergência com outra página oficial: confira antes de aprovar."
                elif all(r["status"] == "confirmed" and not r.get("volatile") for r in live):
                    status, note = "resolved", rule["found"]
                else:
                    status, note = "awaiting_validation", rule["found"] + (" Dado volátil: revisar na próxima consulta." if any(r.get("volatile") for r in live) else "")
                out.append(Resolution(pend["id"], topic, status, note, record_ids))
        return out

    def _pending(self) -> list[dict]:
        try:
            return load_json(self.directory / "pending.json").get("items", [])
        except (OSError, ValueError):
            return []

    def summary(self) -> dict[str, Any]:
        data = self.load()
        resolutions = data.get("resolutions") or [r.to_dict() for r in self.resolve(data)]
        records = data.get("records", [])
        today = self._today()
        stale = [r for r in records if r["status"] != "rejected" and r.get("next_review") and date.fromisoformat(r["next_review"][:10]) < today]
        return {
            "available": bool(data.get("consulted_at")), "consulted_at": data.get("consulted_at"), "next_review": data.get("next_review"),
            "due": self.is_due(), "error": data.get("error"), "security_notice": data.get("security_notice"),
            "counts": dict(Counter(r["status"] for r in records)), "stale_records": len(stale), "offerings": len(data.get("offerings", [])),
            "resolution_counts": dict(Counter(r["status"] for r in resolutions)), "resolutions": resolutions,
            "records": records, "structure": data.get("structure", {}), "fields_discarded": data.get("fields_discarded", []),
            "history": list(reversed(data.get("history", [])))[:10], "storage": self.storage_kind,
        }


# ------------------------------------------------------------------------------------------------ regras de relação com as pendências
def _by_unit(prefix: str, *units: str):
    return lambda records: [f"{prefix}-{u}" for u in units]


RESOLUTION_RULES: dict[str, dict[str, Any]] = {
    "pend-cep-jp-cursos": {"records": _by_unit("unit", "CEP-JP"), "found": "O portal lista turmas do CEP João Pessoa.", "absent": "O portal não listou turmas do CEP João Pessoa na consulta."},
    "pend-cep-jp-eixos": {"records": _by_unit("areas", "CEP-JP"), "found": "O portal traz as áreas dos cursos do CEP-JP; não afirma que sejam os sete eixos tecnológicos.", "absent": "O portal não traz as áreas dos cursos do CEP-JP."},
    "pend-tadros": {"records": _by_unit("contact", "TADROS"), "found": "O portal traz endereço/contato e turmas da unidade Tadros.", "absent": "O portal lista a unidade nos filtros, mas sem endereço, contato ou turmas."},
    "pend-patos": {"records": _by_unit("contact", "PATOS"), "found": "O portal traz endereço/contato e turmas de Patos.", "absent": "O portal lista Patos nos filtros, mas sem endereço, contato ou turmas."},
    "pend-divergencia-cajazeiras": {"records": _by_unit("contact", "CEP-CZ"), "found": "O portal traz o endereço e o telefone do CEP Cajazeiras.", "absent": "O portal não traz o endereço do CEP Cajazeiras."},
    "pend-divergencia-gastronomia": {"records": _by_unit("contact", "GASTRO-HOTELARIA"), "found": "O portal traz o endereço da Escola de Gastronomia e Hotelaria.", "absent": "O portal não traz endereço da Escola de Gastronomia e Hotelaria."},
    "pend-valores-vagas": {"records": lambda r: ["values-vagas", "offer-modalities"], "found": "O portal traz valores, vagas e datas por turma (variam e mudam).", "absent": "O portal não trouxe valores, vagas ou datas."},
    "pend-cendege-reforma": {"records": lambda r: [], "found": "", "absent": "O portal não informa a situação da reforma do CENDEGE."},
    "pend-zona-sul": {"records": lambda r: [], "found": "", "absent": "A Escola Senac Zona Sul não consta entre as unidades do portal; isso não confirma se funciona."},
    "pend-cep-jp-horarios": {"records": lambda r: [], "found": "", "absent": "O portal traz horário de aulas das turmas, não o horário de atendimento das unidades."},
    "pend-psg-processo": {"records": lambda r: [], "found": "", "absent": "O portal não traz o passo a passo do Programa Senac de Gratuidade."},
}


# ------------------------------------------------------------------------------------------------ extração
@dataclass
class PortalResult:
    outcome: str  # extracted | cache | failed | too_soon
    detail: str = ""


class PortalExtractor:
    def __init__(self, directory: Path, kb, fetcher_factory: Callable[[], PoliteFetcher], today: Callable[[], date] = date.today,
                 now: Callable[[], str] = _now, storage: PortalStorage | None = None) -> None:
        self._kb = kb
        self._fetcher_factory = fetcher_factory
        self.store = PortalKnowledge(directory, today, now, storage)
        self._today = today
        self._now = now

    def _source(self):
        source = self._kb.sources.get(SOURCE_ID)
        if source is None:
            raise ValueError("fonte oficial não cadastrada em sources.json")
        return source

    def refresh_if_stale(self) -> PortalResult | None:
        """Atualização automática (inicialização e checagem periódica): baixa de novo só se a última consulta não foi hoje.

        Independente do prazo de revisão por item (REVIEW_DAYS, usado para sinalizar pendências ao operador):
        aqui o critério é só a data. Nunca bloqueia nem derruba a aplicação; falha de rede preserva os dados existentes
        (tratada dentro de refresh()), e qualquer outra falha inesperada (ex.: fonte não cadastrada) é só registrada.
        """
        data = self.store.load()
        consulted_at = data.get("consulted_at")
        if consulted_at and date.fromisoformat(consulted_at[:10]) == self._today():
            return None  # já baixado hoje
        try:
            return self.refresh(force=True)
        except Exception:  # noqa: BLE001 - atualização em segundo plano nunca pode derrubar a aplicação
            logger.exception("Atualização automática diária do portal de cursos técnicos falhou.")
            return None

    def refresh(self, force: bool = False) -> PortalResult:
        """Consulta a fonte (respeitando cache e intervalo mínimo). Em falha, preserva a última extração e registra o erro."""
        data = self.store.load()
        if not force and data.get("consulted_at") and not self.store.is_due():
            return PortalResult("cache", f"Última consulta em {_br(data['consulted_at'])}; próxima revisão em {_br(data.get('next_review', ''))}.")
        last = data.get("last_attempt")
        if last:
            try:
                if datetime.now(timezone.utc) - datetime.fromisoformat(last) < MIN_REFRESH_GAP and not force:
                    return PortalResult("too_soon", "Consulta recente: aguarde alguns minutos.")
            except ValueError:
                pass
        source = self._source()
        stamp = self._now()
        data["last_attempt"] = stamp
        try:
            page, listing = self._download(source.url)
            structure = parse_structure(page)
            turmas, seen, dropped = parse_listing(listing)
        except Exception as error:  # noqa: BLE001 - qualquer falha mantém a última versão válida
            reason = str(error) or type(error).__name__
            logger.warning("Consulta ao portal de cursos técnicos falhou: %s", reason)
            data.update(error=reason, error_at=stamp)
            data.setdefault("history", []).append({"at": stamp, "kind": "falha", "summary": f"Consulta falhou: {reason}"})
            data["history"] = data["history"][-HISTORY_LIMIT:]
            if not data.get("records"):  # nada foi extraído antes: as pendências relacionadas ficam "consulta falhou"
                data["resolutions"] = [r.to_dict() for r in self.store.resolve(data)]
            self.store.save(data)  # com extração anterior: resoluções e registros permanecem intactos
            return PortalResult("failed", reason)
        unit_of = lambda text: (self._kb.detect_units(text) or [None])[0]  # noqa: E731
        offerings = [normalize_offering(t, unit_of) for t in turmas if t.get("CODI_TURMA") is not None]
        review = (self._today() + timedelta(days=REVIEW_DAYS)).isoformat()
        records = self._build_records(structure, offerings, stamp, review)
        merged = self._merge(data.get("records", []), records)
        data.update(
            source_id=SOURCE_ID, url=source.url, name=source.name, category=source.category or CATEGORY, institution="Senac PB", kind="Fonte oficial",
            consulted_at=stamp, next_review=review, error=None, error_at=None, structure=structure, offerings=offerings, records=merged,
            fields_seen=seen, fields_discarded=dropped,
            security_notice=("O endpoint público do portal devolve, junto com as turmas, campos de credenciais de pagamento. Eles foram descartados e não são "
                             "gravados nem exibidos; recomenda-se avisar o Senac PB.") if dropped else None,
        )
        data["resolutions"] = [r.to_dict() for r in self.store.resolve(data)]
        for resolution in data["resolutions"]:
            for rid in resolution["record_ids"]:
                rec = next((r for r in merged if r["id"] == rid), None)
                if rec is not None and resolution["pending_id"] not in rec["pending_ids"]:
                    rec["pending_ids"].append(resolution["pending_id"])
        data.setdefault("history", []).append({"at": stamp, "kind": "consulta", "summary": f"{len(offerings)} turma(s), {len(merged)} registro(s) organizados."})
        data["history"] = data["history"][-HISTORY_LIMIT:]
        persisted = self.store.save(data)
        detail = f"{len(offerings)} turmas e {len(merged)} registros."
        if not persisted:  # o chat já usa o dado novo, mas ele se perde no próximo reinício
            detail += " Aviso: banco de dados indisponível; a extração vale só até o robô reiniciar."
        return PortalResult("extracted", detail)

    def _download(self, page_url: str) -> tuple[str, str]:
        fetcher = self._fetcher_factory()
        allowed = ["senac.br"]
        response, problem = fetcher.fetch(page_url, lambda u: is_official_url(u, allowed), "endereço fora dos domínios oficiais")
        if response is None:
            raise RuntimeError(problem)
        if response.status_code != 200:
            raise RuntimeError(f"HTTP {response.status_code} na página")
        page = response.text
        filters = {"search": "", "nivel": [], "area": "", "cidade": "", "unidade": "", "tpFormacao": [], "turnos": [], "dataInicial": "", "dataFinal": ""}
        listing_url = urllib.parse.urljoin(page_url, LISTING_FILE) + "?json=" + urllib.parse.quote(json.dumps(filters, separators=(",", ":")))
        listing, problem = fetcher.fetch(listing_url, lambda u: is_official_url(u, allowed), "endereço fora dos domínios oficiais")
        if listing is None:
            raise RuntimeError(f"listagem de turmas: {problem}")
        if listing.status_code != 200:
            raise RuntimeError(f"HTTP {listing.status_code} na listagem de turmas")
        return page, listing.text

    # ---------------------------------------------------------------- registros
    def _unit_entries(self, key: str) -> list:
        return [e for e in self._kb.entries if e.unit == key and e.category == "units"]

    def _build_records(self, structure: dict[str, list[str]], offerings: list[dict[str, Any]], stamp: str, review: str) -> list[dict[str, Any]]:
        day = _br(stamp)
        out: list[dict[str, Any]] = []
        add = out.append
        labels = {"cidades": "Cidades", "unidades": "Unidades", "segmentos": "Segmentos", "modalidades": "Modalidades", "tipos_formacao": "Tipos de formação", "turnos": "Turnos"}
        for key, label in labels.items():
            values = [_title(v) if key in ("cidades", "unidades") else v for v in structure.get(key, [])]
            if values:
                add(_record(f"struct-{key}", "structure", f"Portal de cursos técnicos: {label.lower()} nos filtros",
                            f"O portal de matrículas do Senac Paraíba permite filtrar as turmas por {label.lower()}: {_join(values, 12)}.", stamp, review, "found"))
        if structure.get("tem_carrinho"):
            add(_record("struct-matricula", "structure", "Portal de cursos técnicos: matrícula",
                        "O portal de matrículas lista as turmas com filtros por cidade, unidade, segmento, modalidade, tipo de formação, turno e período, e tem carrinho de compras.",
                        stamp, review, "found"))
        by_unit: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for o in offerings:
            by_unit[o["unidade_chave"] or "sem-unidade:" + o["unidade"]].append(o)
        for ukey, rows in by_unit.items():
            slug = ukey if not ukey.startswith("sem-unidade:") else normalize(ukey.split(":", 1)[1]).replace(" ", "-")
            name = rows[0]["unidade"]
            courses = Counter(r["curso"] for r in rows)
            unit_key = ukey if not ukey.startswith("sem-unidade:") else None
            add(_record(f"unit-{slug}", "unit_courses", f"Cursos listados no portal: {name}",
                        f"Na consulta de {day}, o portal de matrículas listava {len(rows)} turma(s) em {name} ({rows[0]['cidade']}), em {len(courses)} curso(s) diferente(s), como: {_join([c for c, _ in courses.most_common()], 6)}.",
                        stamp, review, "awaiting_validation", unit=unit_key, volatile=True, note="Lista de turmas muda com frequência; o robô só a cita com a data da consulta."))
            areas = Counter(r["area"] for r in rows if r["area"])
            if areas:
                add(_record(f"areas-{slug}", "unit_areas", f"Áreas dos cursos listados: {name}",
                            f"Na consulta de {day}, as turmas de {name} estavam nas áreas: {_join([a for a, _ in areas.most_common()], 10)}.",
                            stamp, review, "awaiting_validation", unit=unit_key, volatile=True, note="Áreas do portal; não são necessariamente os eixos tecnológicos da unidade."))
            contact = self._contact_record(slug, unit_key, name, rows, stamp, review)
            if contact:
                add(contact)
        levels = Counter(o["modalidade"] or "Sem modalidade" for o in offerings)
        if levels:
            add(_record("offer-modalities", "offer", "Modalidades das turmas listadas no portal",
                        f"Na consulta de {day}, as turmas listadas por modalidade eram: " + _join([f"{k}: {v}" for k, v in levels.most_common()], 6) + ".",
                        stamp, review, "awaiting_validation", volatile=True))
        schooling = Counter(o["escolaridade"] for o in offerings if o["escolaridade"])
        ages = Counter(str(o["idade_minima"]) for o in offerings if o["idade_minima"] not in (None, "", 0))
        if schooling or ages:
            text = "Requisitos de ingresso informados nas turmas (variam por curso)"
            if not schooling:
                text += "; o portal não informou escolaridade mínima nas turmas listadas"
            if schooling:
                text += ": escolaridade — " + _join([f"{k} ({v} turma(s))" for k, v in schooling.most_common()], 4)
            if ages:
                text += "; idade mínima — " + _join([f"{k} anos ({v})" for k, v in ages.most_common()], 4)
            add(_record("requirements", "requirements", "Requisitos de ingresso nas turmas do portal", text + ".", stamp, review, "awaiting_validation",
                        volatile=True, note="Confirmar no detalhe de cada turma antes de afirmar requisitos a um visitante."))
        with_seats = sum(1 for o in offerings if _num(o["volatil"].get("VAGASDISPONIVEIS")) > 0)
        free = sum(1 for o in offerings if _num(o["volatil"].get("VALORCURSO")) == 0 and _num(o["volatil"].get("VALOR_MATRICULA")) == 0)
        add(_record("values-vagas", "volatile", "Valores e vagas no portal (dado volátil)",
                    f"Na consulta de {day}, {with_seats} de {len(offerings)} turmas listadas tinham vagas e {free} eram gratuitas. Valores e vagas variam por turma e mudam a toda hora.",
                    stamp, review, "awaiting_validation", volatile=True, speakable=True,
                    note="O robô fala valores, vagas, datas e horários das turmas, sempre com a data da consulta e a ressalva de que mudam."))
        return out

    def _contact_record(self, slug: str, unit_key: str | None, name: str, rows: list[dict[str, Any]], stamp: str, review: str) -> dict[str, Any] | None:
        addresses = Counter((r["endereco"]["logradouro"], r["endereco"]["numero"], r["endereco"]["bairro"], r["endereco"]["cep"], r["endereco"]["telefone"]) for r in rows if r["endereco"]["logradouro"])
        if not addresses:
            return None
        (street, number, district, cep, phone), _ = addresses.most_common(1)[0]
        parts = [p for p in (f"{street}, {number}" if number else street, district, rows[0]["cidade"]) if p]
        content = (f"Segundo o portal de matrículas, {name} fica em {', '.join(parts)}" + (f", CEP {cep[:5]}-{cep[5:]}" if len(cep) == 8 else "")
                   + (f", telefone ({phone[:2]}) {phone[2:-4]}-{phone[-4:]}" if len(phone) in (10, 11) else "") + ".")
        status, note = "found", "Sem informação anterior para comparar."
        entries = self._unit_entries(unit_key) if unit_key else []
        entry = entries[0] if entries else None
        entry_ids = ", ".join(e.id for e in entries)
        # pendências de DIVERGÊNCIA ligadas a esta unidade: o que as páginas oficiais já diziam entra na comparação
        divergence = [p for p in self.store._pending() if p.get("type") == "divergence" and f"contact-{slug}" in RESOLUTION_RULES.get(p.get("id", ""), {}).get("records", lambda r: [])({})]
        known = " ".join(e.content for e in entries) + " " + " ".join(p.get("reason", "") for p in divergence)
        if known.strip():
            digits = re.sub(r"\D", "", known)
            checks = {
                "endereço": bool(street) and normalize(street.split()[-1]) in normalize(known) and bool(number) and re.search(rf"\b{number}\b", known) is not None,
                "telefone": (not phone) or phone[-8:] in digits,
            }
            has_address = bool(re.search(r"\bav\.|avenida|\brua\b|\br\.", known, re.IGNORECASE))
            has_phone = bool(re.search(r"\d{4}-?\d{4}", known))
            wrong = [k for k, ok in checks.items() if not ok and ((k == "endereço" and has_address) or (k == "telefone" and has_phone))]
            if divergence:
                status = "awaiting_validation"
                note = ("As páginas oficiais já divergiam neste ponto (pendência). " + ("O portal coincide com uma das versões já registradas." if checks["endereço"] else "O portal traz uma versão diferente das já registradas.")
                        + " O portal não resolve a divergência sozinho: a decisão é do operador.")
            elif wrong:
                status = "divergent"
                note = f"Difere do que consta na base ({entry_ids or 'pendência'}): " + " e ".join(wrong) + ". Confira antes de aprovar."
            elif checks["endereço"] or (has_phone and checks["telefone"]):
                status, note = "confirmed", f"Coincide com a página oficial já registrada ({entry_ids or 'base'}): duas páginas oficiais concordam."
        return _record(f"contact-{slug}", "contact", f"Endereço e contato no portal: {name}", content, stamp, review, status, unit=unit_key, note=note,
                       approved_by="fonte oficial (duas páginas coincidem)" if status == "confirmed" else None)

    @staticmethod
    def _merge(previous: list[dict[str, Any]], new: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Decisões do operador são preservadas: versão aprovada nunca é trocada por dado novo (vira proposta); rejeitada não volta."""
        old = {r["id"]: r for r in previous}
        merged: list[dict[str, Any]] = []
        for record in new:
            before = old.get(record["id"])
            if before is None:
                merged.append(record)
                continue
            if before["status"] == "rejected":
                merged.append(before)
            elif before.get("approved_by") == "operator":
                if normalize(before["content"]) != normalize(record["content"]):
                    before["update_proposal"] = {"content": record["content"], "consulted_at": record["consulted_at"]}
                before["next_review"] = record["next_review"]
                merged.append(before)
            else:
                record["pending_ids"] = before.get("pending_ids", [])
                merged.append(record)
        keep_ids = {r["id"] for r in new}
        for before in previous:  # registro que não aparece mais na fonte: desatualizado, nunca apagado
            if before["id"] not in keep_ids:
                if before["status"] != "rejected":  # a decisão de rejeitar é preservada mesmo se o registro sumir da fonte
                    before["status"] = "stale"
                    before["note"] = "Não aparece na última consulta da fonte."
                merged.append(before)
        return merged


def _num(value: Any) -> float:
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


# ------------------------------------------------------------------------------------------------ fala de uma turma
MONTHS = ("janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro")
CEP_JP_KEY = "CEP-JP"
DETAIL_QUESTION = re.compile(
    r"\b(valor|valores|preco|precos|quanto|custa|custo|custar|pagar|mensalidade|vagas?|horario|horarios|"
    r"quando comeca|quando inicia|comeca|inicio|datas?|carga horaria|duracao|turno|turnos)\b")


def _spoken_date(iso: str, today: date | None = None) -> str:
    try:
        parsed = date.fromisoformat(str(iso)[:10])
    except ValueError:
        return ""
    text = f"{parsed.day} de {MONTHS[parsed.month - 1]}"
    return text if today is None or parsed.year == today.year else f"{text} de {parsed.year}"


spoken_date = _spoken_date  # nome público (usado pela orientação de cursos)


def _spoken_money(value: Any) -> str:
    """222.6 -> '222 reais e 60 centavos' (nunca arredonda: o valor é falado como a fonte informa)."""
    cents = round(_num(value) * 100)
    reais, centavos = divmod(cents, 100)
    base = f"{reais} {'real' if reais == 1 else 'reais'}"
    return base if not centavos else (f"{base} e {centavos} centavos" if reais else f"{centavos} centavos")


def _spoken_hours(value: Any) -> str:
    hours = _num(value)
    if hours <= 0:
        return ""
    whole = int(hours) if hours == int(hours) else hours
    return f"{whole} {'hora' if whole == 1 else 'horas'}"


def spoken_turma(offering: dict[str, Any], today: date | None = None) -> str:
    """Texto falável de UMA turma: unidade, datas, dias, horário, carga horária, valor e vagas, só com dados da fonte."""
    unit = offering.get("unidade") or "unidade não informada"
    city = offering.get("cidade") or ""
    where = f"{unit}, em {city}" if city and city.lower() not in unit.lower() else unit
    parts = [f"{offering['curso']}, na unidade {where}."]
    start, end = offering.get("inicio") or "", offering.get("fim") or ""
    when = []
    if start:
        started = bool(today and start < today.isoformat())
        when.append(f"{'Começou' if started else 'Começa'} em {_spoken_date(start, today)}")
    if end and end != start:
        when.append(f"termina em {_spoken_date(end, today)}")
    schedule = []
    if offering.get("dias"):
        schedule.append(str(offering["dias"]).lower())
    schedule_hours = str(offering.get("horario") or "")
    if schedule_hours:
        schedule.append(f"das {schedule_hours}" if " às " in schedule_hours else schedule_hours)
    if when:
        parts.append(", ".join(when) + (f", {', '.join(schedule)}" if schedule else "") + ".")
    elif schedule:
        parts.append(f"{', '.join(schedule).capitalize()}.")
    hours = _spoken_hours(offering.get("carga_horaria"))
    if hours:
        parts.append(f"A carga horária é de {hours}.")
    volatile = offering.get("volatil") or {}
    if "VALORCURSO" in volatile:
        price, fee = _num(volatile.get("VALORCURSO")), _num(volatile.get("VALOR_MATRICULA"))
        if price:
            parts.append(f"O valor do curso é de {_spoken_money(price)}" + (f", mais {_spoken_money(fee)} de matrícula." if fee else "."))
        else:
            parts.append("Nesta turma não há custo." if not fee else f"O curso não tem mensalidade, e a matrícula é de {_spoken_money(fee)}.")
    if "VAGASDISPONIVEIS" in volatile:
        seats = int(_num(volatile.get("VAGASDISPONIVEIS")))
        parts.append("Não restam vagas na consulta." if seats <= 0 else ("É 1 vaga." if seats == 1 else f"São {seats} vagas."))
    return " ".join(parts)


# ------------------------------------------------------------------------------------------------ consulta para o chat
@dataclass
class PortalAnswer:
    text: str
    consulted_at: str
    offering_ids: list[Any]


STOP = {"curso", "cursos", "tecnico", "tecnicos", "senac", "paraiba", "tem", "ha", "quais", "que", "qual", "oferece", "oferecem", "oferta", "turma", "turmas", "formacao",
        "disponiveis", "disponivel", "cidade", "unidade", "da", "de", "do", "em", "no", "na", "para", "voces", "tenho", "tem",
        # Verbos/expressões de interesse que a orientação de cursos (backend/guidance/engine.py) também reconhece:
        # chegam até aqui dentro da frase do visitante ("quero fazer um curso de X") e não são palavras do CURSO em si.
        "quero", "queria", "gostaria", "pretendo", "procuro", "procurando", "interesse", "interessa", "interessado", "interessada",
        "sonho", "vontade", "pensando", "penso", "preciso", "fazer", "gosto", "adoro", "amo", "trabalhar", "trabalho",
        "estudar", "aprender", "capacitar", "capacitacao", "qualificacao", "qualificar", "especializar", "algum", "alguma",
        "outro", "outra", "voce", "vc", "pode", "poderia", "favor", "obrigado", "obrigada",
        # Palavras sobre A GRADE/PROGRAMAÇÃO em si ("qual é a grade de cursos... atualmente?"), não sobre um
        # curso específico: sem isso, a exigência de "todas as palavras precisam aparecer no curso" nunca
        # bate (nenhuma turma real contém a palavra "grade"), e a pergunta falha mesmo quando a unidade tem
        # turmas confirmadas. Sem nenhuma palavra de curso sobrando, a consulta lista a programação inteira
        # da unidade (mesmo comportamento já usado para "quais cursos o CEP João Pessoa oferece?").
        # Em forma já radicalizada (tokenize() aplica stem() antes deste filtro): plural vira singular etc.
        "grade", "programacao", "atualmente", "atual", "vigente", "completa", "completo", "geral", "todo",
        "toda", "lista", "listagem", "ofertado", "ofertada", "oferecido", "oferecida", "andamento", "momento",
        "existente",
        # Verbos de pedir/contar e palavras vagas de preenchimento ("me fala sobre...", "tem alguma coisa de...").
        "fala", "falar", "falam", "conte", "contar", "diga", "dizer", "explica", "explicar", "mostra", "mostrar",
        "coisa", "coisas", "negocio", "disso", "sobre", "algo", "area", "areas", "assunto", "tipo", "tipos"}


class PortalLookup:
    """Consulta o CACHE da extração (nunca a rede) para perguntas sobre cursos técnicos que a base local não responde com segurança."""

    def __init__(self, portal: PortalKnowledge, kb, clock: Callable[[], date] = date.today) -> None:
        self._portal = portal
        self._kb = kb
        self._clock = clock

    def has_data(self) -> bool:
        data = self._portal.load()
        return bool(data.get("offerings")) and bool(data.get("consulted_at"))

    def get_turma(self, turma_id: str) -> dict[str, Any] | None:
        """Turma da última extração pelo id 'turma-N' (o mesmo usado nas respostas); None se não existir mais."""
        return next((o for o in self._portal.load().get("offerings") or [] if f"turma-{o['id']}" == turma_id), None)

    def consulted_label(self) -> str:
        """Data da última consulta no formato falado: '10 de novembro'."""
        return _spoken_date(str(self._portal.load().get("consulted_at") or "")) or ""

    def describe(self, offering: dict[str, Any]) -> str:
        """Turma falada com todos os dados (datas, horário, carga horária, valor e vagas) + data da consulta e ressalva."""
        label = self.consulted_label()
        note = (f"Dados do portal oficial de matrículas, consultado em {label}; " if label else "Dados do portal oficial de matrículas; ")
        return f"{spoken_turma(offering, self._clock())} {note}valores e vagas mudam, então confirme na matrícula."

    def find(self, message: str, exclude: frozenset[str] | set[str] = frozenset()) -> list[dict[str, Any]]:
        """Turmas ABERTAS (já na extração, sem rede) que casam com o assunto, na ordem de prioridade da orientação:
        1) CEP João Pessoa; 2) demais unidades do Senac PB (por relevância e data de início). `exclude`: ids "turma-N" já oferecidos.
        Sem palavra de assunto (pedido genérico) devolve vazio: quem decide o que perguntar é a orientação."""
        data = self._portal.load()
        offerings = data.get("offerings") or []
        if not offerings or not data.get("consulted_at"):
            return []
        words = self._topic_words(message, offerings)
        if not words:
            return []
        today = self._clock().isoformat()
        found: list[tuple[tuple, dict[str, Any]]] = []
        for o in offerings:
            if f"turma-{o['id']}" in exclude or (o.get("fim") and o["fim"] < today):
                continue
            volatile = o.get("volatil") or {}
            if "VAGASDISPONIVEIS" in volatile and _num(volatile.get("VAGASDISPONIVEIS")) <= 0:
                continue  # turma cheia não é "turma aberta"
            hit = words & set(tokenize(" ".join([o["curso"], o["segmento"], o["area"], o["modalidade"]])))
            if len(hit) < len(words):
                continue
            found.append(((0 if o.get("unidade_chave") == CEP_JP_KEY else 1, o["curso"].lower().startswith("palestra"), o.get("inicio") or "", len(o["curso"])), o))
        found.sort(key=lambda pair: pair[0])
        return [o for _, o in found]

    def _topic_words(self, message: str, offerings: list[dict[str, Any]]) -> set[str]:
        place_words = set(tokenize(" ".join({o["cidade"] for o in offerings} | {o["unidade"] for o in offerings})))
        # Palavras de preço/vaga/horário/data ("quanto custa o curso de Excel?") não são o NOME do curso: saem da busca.
        subject = DETAIL_QUESTION.sub(" ", normalize(message))
        return {t for t in tokenize(subject) if t not in STOP and t not in place_words and len(t) > 3}

    def public_numbers(self) -> frozenset[str]:
        """Telefones e CEPs que as próprias turmas do portal oficial já trazem (mesma fonte oficial do Senac PB,
        só outro canal): usado para a política de saída não tratar esses números como vazamento de dado pessoal
        quando a resposta cita local e contato de uma unidade (ver ChatService)."""
        numbers: set[str] = set()
        for offering in self._portal.offerings():
            endereco = offering.get("endereco") or {}
            for value in (endereco.get("telefone"), endereco.get("cep")):
                digits = re.sub(r"\D", "", str(value or ""))
                if digits:
                    numbers.add(digits)
        return frozenset(numbers)

    def answer(self, message: str, limit: int = 3) -> PortalAnswer | None:
        data = self._portal.load()
        offerings = data.get("offerings") or []
        if not offerings or not data.get("consulted_at"):
            return None
        units = self._kb.detect_units(message)
        cities = {c for c in {o["cidade"] for o in offerings} if set(tokenize(c)) <= set(tokenize(message))}
        # IMPORTANTE: filtrar aqui pelo vocabulário real das turmas (em vez de manter STOP à mão) pareceria mais
        # robusto, mas erra pro lado perigoso: uma palavra ausente de toda a base (ex.: "astronomia", que nenhuma
        # turma tem) ficaria indistinguível de uma palavra de preenchimento (ex.: "grade") e a busca passaria a
        # listar turmas SEM RELAÇÃO com o assunto, em vez de dizer honestamente que não encontrou. Por isso só
        # STOP (lista curada) filtra aqui: no pior caso, uma palavra de preenchimento nova faz a busca responder
        # "não encontrei" (seguro); nunca mostra um curso errado como se respondesse à pergunta.
        words = self._topic_words(message, offerings)
        if not units and not cities and not words:
            return None  # pergunta geral demais: segue na base curada
        scope_name = next((o["unidade"] for o in offerings if o["unidade_chave"] in units), None) if units else (sorted(cities)[0] if cities else None)
        scope = f" em {scope_name}" if scope_name else ""
        pool = [o for o in offerings if (not units or o["unidade_chave"] in units) and (not cities or o["cidade"] in cities)]
        matches = []
        for o in pool:
            hit = words & set(tokenize(" ".join([o["curso"], o["segmento"], o["area"], o["modalidade"]])))
            if words and len(hit) < len(words):
                continue  # todos os termos do curso precisam aparecer
            matches.append((len(hit), o))
        if not matches:
            if not words or not scope_name:
                return None  # só afirma ausência quando a pergunta tem unidade/cidade (a consulta cobre aquela lista)
            return PortalAnswer(f"Não encontrei turmas desse assunto{scope} no portal oficial de matrículas do Senac Paraíba. "
                                "As turmas mudam: confirme no portal.", data["consulted_at"], [])
        matches.sort(key=lambda m: (-m[0], m[1]["curso"].lower().startswith("palestra"), len(m[1]["curso"]), m[1]["inicio"]))
        if words and DETAIL_QUESTION.search(normalize(message)):  # perguntou valor/vaga/horário/data: fala os dados das turmas mais relevantes
            top = [o for _, o in matches][:2]
            return PortalAnswer(" ".join(self.describe(o) if i == 0 else spoken_turma(o, self._clock()) for i, o in enumerate(top)),
                                data["consulted_at"], [o["id"] for o in top])
        text = self._grouped_text([o for _, o in matches], limit)
        return PortalAnswer(text, data["consulted_at"], [o["id"] for _, o in matches][:limit * MAX_COURSES_PER_UNIT])

    def _grouped_text(self, matched_offerings: list[dict], max_units: int) -> str:
        """Cursos agrupados por unidade, cada uma com local e contato (nunca preço, carga horária ou vagas)."""
        groups: dict[str, list[dict]] = {}
        for offering in matched_offerings:
            groups.setdefault(offering["unidade"] or "unidade não informada", []).append(offering)
        parts = []
        for unit_name, offs in list(groups.items())[:max_units]:
            names = list(dict.fromkeys(o["curso"] for o in offs if len(o["curso"]) <= 60))[:MAX_COURSES_PER_UNIT] or [offs[0]["curso"]]
            address = _address_text(offs[0].get("endereco") or {})
            place = f"{unit_name} ({address})" if address else unit_name
            parts.append(f"{_join(names, MAX_COURSES_PER_UNIT)} em {place}")
        return f"Há turmas de {'; e de '.join(parts)}. Turmas, valores e vagas mudam: confirme no portal."


def main() -> int:  # python -m backend.knowledge.portal [--force | --if-stale]
    """--force: consulta sempre. --if-stale: consulta só se a última consulta não foi hoje (uso na inicialização diária)."""
    import sys  # noqa: PLC0415

    from backend.knowledge import KnowledgeBase  # noqa: PLC0415
    from backend.knowledge.updater import USER_AGENT  # noqa: PLC0415

    directory = Path(__file__).resolve().parent.parent.parent / "knowledge"
    kb = KnowledgeBase.load(directory)
    extractor = PortalExtractor(directory, kb, lambda: PoliteFetcher(USER_AGENT))
    if "--if-stale" in sys.argv:
        result = extractor.refresh_if_stale()
        print("cache - a programação já foi consultada hoje." if result is None else f"{result.outcome} - {result.detail}")
        return 0 if result is None or result.outcome != "failed" else 1
    result = extractor.refresh(force="--force" in sys.argv)
    print(result.outcome, "-", result.detail)
    summary = extractor.store.summary()
    print("resolução das pendências:", summary["resolution_counts"])
    return 0 if result.outcome != "failed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
