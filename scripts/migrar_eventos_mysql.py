r"""Copia os eventos de events/ (arquivos) para o MySQL configurado no .env. Uso:
    .\.venv\Scripts\python.exe scripts\migrar_eventos_mysql.py [--sobrescrever]
Não apaga nada na origem. Documentos já existentes no banco são preservados, a menos que --sobrescrever."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import load_settings  # noqa: E402
from backend.eventkb.storage import FileStorage, MySQLStorage  # noqa: E402


def main() -> int:
    s = load_settings()
    if not (s.db_host and s.db_name and s.db_user):
        print("Configure DB_HOST, DB_NAME, DB_USER e DB_PASSWORD no .env.")
        return 1
    overwrite = "--sobrescrever" in sys.argv
    root = Path(__file__).resolve().parent.parent / s.events_dir
    src = FileStorage(root)
    dst = MySQLStorage(s.db_host, s.db_port, s.db_name, s.db_user, s.db_password, s.db_charset, s.db_ssl, cache_seconds=0)
    copied = skipped = 0
    keys = ["active.json"] if src.exists("active.json") else []
    for event_id in src.event_ids():
        for path in sorted((root / event_id).rglob("*.json")):
            keys.append(path.relative_to(root).as_posix())
    for key in keys:
        data = src.read(key)
        if data is None:
            continue
        if dst.exists(key) and not overwrite:
            skipped += 1
            continue
        dst.write(key, data)
        copied += 1
    print(f"Copiados: {copied}; já existiam (preservados): {skipped}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
