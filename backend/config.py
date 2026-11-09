"""Configuração centralizada por variáveis de ambiente (.env opcional)."""
import logging
import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("senac_bot.config")

SUPPORTED_ROBOT_MODES = ("simulation", "physical")
# Padrão apenas inicial; o modelo real vem de GEMINI_MODEL (consulte a lista oficial de modelos).
DEFAULT_GEMINI_MODEL = "gemini-3.5-flash-lite"


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    log_level: str
    app_env: str
    robot_mode: str
    gemini_api_key: str
    gemini_model: str
    gemini_timeout_seconds: float
    gemini_max_retries: int
    knowledge_dir: str
    events_dir: str
    event_external_search: bool
    event_auto_update: bool
    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_password: str
    db_charset: str
    db_ssl: bool


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("Valor inválido em %s=%r; usando %d.", name, raw, default)
        return default


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        value = 0.0
    if value <= 0:
        logger.warning("Valor inválido em %s=%r; usando %s.", name, raw, default)
        return default
    return value


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "sim", "yes", "on")


def load_settings() -> Settings:
    robot_mode = (os.getenv("ROBOT_MODE", "").strip() or "simulation").lower()
    if robot_mode not in SUPPORTED_ROBOT_MODES:
        logger.warning(
            "ROBOT_MODE=%r não é suportado nesta versão; usando 'simulation'.", robot_mode
        )
        robot_mode = "simulation"
    return Settings(
        host=os.getenv("SENAC_HOST", "").strip() or "127.0.0.1",
        port=_int_env("SENAC_PORT", 8000),
        log_level=(os.getenv("SENAC_LOG_LEVEL", "").strip() or "INFO").upper(),
        app_env=os.getenv("APP_ENV", "").strip() or "development",
        robot_mode=robot_mode,
        gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
        gemini_model=os.getenv("GEMINI_MODEL", "").strip() or DEFAULT_GEMINI_MODEL,
        gemini_timeout_seconds=_float_env("GEMINI_TIMEOUT_SECONDS", 10.0),
        gemini_max_retries=max(0, min(_int_env("GEMINI_MAX_RETRIES", 1), 3)),
        knowledge_dir=os.getenv("KNOWLEDGE_DIR", "").strip() or "knowledge",
        events_dir=os.getenv("EVENTS_DIR", "").strip() or "events",
        event_external_search=_bool_env("EVENT_EXTERNAL_SEARCH", True),
        event_auto_update=_bool_env("EVENT_AUTO_UPDATE", True),
        db_host=os.getenv("DB_HOST", "").strip(),
        db_port=_int_env("DB_PORT", 3306),
        db_name=os.getenv("DB_NAME", "").strip(),
        db_user=os.getenv("DB_USER", "").strip(),
        db_password=os.getenv("DB_PASSWORD", ""),
        db_charset=os.getenv("DB_CHARSET", "").strip() or "utf8mb4",
        db_ssl=_bool_env("DB_SSL", False),
    )
