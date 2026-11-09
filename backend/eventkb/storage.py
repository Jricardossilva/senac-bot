"""Armazenamento de baixo nível do Gerenciador de Eventos: documentos JSON endereçados por chave ("<evento>/event.json").

- FileStorage: arquivos em disco (padrão; escrita atômica com cópia .bak). Usado no desenvolvimento local.
- MySQLStorage: tabela única no MySQL (ex.: Hostinger), para sobreviver a reinícios do Render (disco efêmero).
O EventStore só conhece esta interface; a regra de negócio não muda com o armazenamento.
"""
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Protocol

logger = logging.getLogger("senac_bot.eventkb.storage")

TABLE = "senacbot_event_docs"


class StorageError(Exception):
    """Armazenamento indisponível. A mensagem é segura para o operador (sem host, usuário ou senha)."""


class DocStorage(Protocol):
    def read(self, key: str) -> Any | None: ...
    def write(self, key: str, data: Any) -> None: ...
    def exists(self, key: str) -> bool: ...
    def event_ids(self) -> list[str]: ...


# ---------------------------------------------------------------------- arquivos
class FileStorage:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.root.joinpath(*key.split("/"))

    def read(self, key: str) -> Any | None:
        """Arquivo ausente = None; corrompido = tenta a cópia de segurança, senão None (sem derrubar)."""
        path = self._path(key)
        bak = path.with_suffix(path.suffix + ".bak")
        for candidate in (path, bak):
            try:
                return json.loads(candidate.read_text(encoding="utf-8"))
            except FileNotFoundError:
                if candidate == path and not bak.exists():
                    return None
            except (OSError, ValueError):
                logger.error("Arquivo ilegível: %s", candidate)
        return None

    def write(self, key: str, data: Any) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if path.exists():
            try:
                os.replace(path, path.with_suffix(path.suffix + ".bak"))
            except OSError:
                logger.warning("Não foi possível criar a cópia de segurança de %s.", path.name)
        os.replace(tmp, path)

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def event_ids(self) -> list[str]:
        return sorted(p.name for p in self.root.iterdir() if p.is_dir())


# ---------------------------------------------------------------------- MySQL
class MySQLStorage:
    """Uma tabela (chave -> JSON). Conexões curtas, consultas parametrizadas, cache de leitura de poucos segundos.

    Se o banco cair, leituras devolvem o último valor em cache (o chat segue respondendo); escritas falham com
    StorageError (nunca finge que gravou).
    """

    def __init__(
        self,
        host: str,
        port: int,
        database: str,
        user: str,
        password: str,
        charset: str = "utf8mb4",
        use_ssl: bool = False,
        connect_timeout: float = 5.0,
        cache_seconds: float = 5.0,
        connect=None,
    ) -> None:
        self._params = dict(
            host=host, port=port, database=database, user=user, password=password, charset=charset,
            connect_timeout=connect_timeout, read_timeout=connect_timeout * 2, write_timeout=connect_timeout * 2,
            autocommit=True,
        )
        self._use_ssl = use_ssl
        self._connect_fn = connect  # injetável nos testes
        self._cache_seconds = cache_seconds
        self._cache: dict[str, tuple[float, Any]] = {}
        self._ids_cache: tuple[float, list[str]] | None = None
        self._lock = threading.RLock()
        self._ensure_schema()

    # -- conexão
    def _connect(self):
        if self._connect_fn is not None:
            return self._connect_fn()
        import pymysql  # noqa: PLC0415  (só necessário quando o MySQL está configurado)
        params = dict(self._params)
        if self._use_ssl:
            params["ssl"] = {}  # TLS com os certificados do sistema
        return pymysql.connect(**params)

    def _run(self, sql: str, args: tuple = (), fetch: bool = False):
        try:
            conn = self._connect()
            try:
                with conn.cursor() as cur:
                    cur.execute(sql, args)
                    return cur.fetchall() if fetch else None
            finally:
                conn.close()
        except Exception as exc:  # noqa: BLE001  (erros do driver variam; não vazar credenciais)
            logger.error("Falha no MySQL (%s): %s", type(exc).__name__, getattr(exc, "args", ("",))[:1])
            raise StorageError("Banco de dados indisponível no momento.") from None

    def _ensure_schema(self) -> None:
        self._run(
            f"CREATE TABLE IF NOT EXISTS {TABLE} ("
            "doc_key VARCHAR(190) NOT NULL PRIMARY KEY, "
            "event_id VARCHAR(90) NOT NULL, "
            "body LONGTEXT NOT NULL, "
            "updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP, "
            "KEY idx_event (event_id)"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
        )

    # -- interface
    def read(self, key: str) -> Any | None:
        now = time.monotonic()
        with self._lock:
            hit = self._cache.get(key)
            if hit and now - hit[0] < self._cache_seconds:
                return hit[1]
        try:
            rows = self._run(f"SELECT body FROM {TABLE} WHERE doc_key = %s", (key,), fetch=True)
        except StorageError:
            if hit:  # banco fora: serve o último valor conhecido
                return hit[1]
            raise
        try:
            value = json.loads(rows[0][0]) if rows else None
        except ValueError:
            logger.error("Documento ilegível no banco: %s", key)
            value = None
        with self._lock:
            self._cache[key] = (now, value)
        return value

    def write(self, key: str, data: Any) -> None:
        event_id = key.split("/", 1)[0] if "/" in key else ""
        body = json.dumps(data, ensure_ascii=False)
        self._run(
            f"INSERT INTO {TABLE} (doc_key, event_id, body) VALUES (%s, %s, %s) "
            "ON DUPLICATE KEY UPDATE body = VALUES(body)",
            (key, event_id, body),
        )
        with self._lock:
            self._cache[key] = (time.monotonic(), json.loads(body))
            self._ids_cache = None

    def exists(self, key: str) -> bool:
        return self.read(key) is not None

    def event_ids(self) -> list[str]:
        now = time.monotonic()
        with self._lock:
            if self._ids_cache and now - self._ids_cache[0] < self._cache_seconds:
                return list(self._ids_cache[1])
        try:
            rows = self._run(f"SELECT event_id FROM {TABLE} WHERE doc_key = CONCAT(event_id, '/event.json') ORDER BY event_id", fetch=True)
        except StorageError:
            if self._ids_cache:
                return list(self._ids_cache[1])
            raise
        ids = [r[0] for r in rows]
        with self._lock:
            self._ids_cache = (now, ids)
        return list(ids)
