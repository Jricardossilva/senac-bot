"""Ponto de entrada do backend FastAPI do SENAC BOT."""
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from backend.config import load_settings
from backend.errors import RobotError, register_error_handlers
from backend.events import EventManager
from backend.hardware.simulator import SimulatedHardware
from backend.preflight import build_preflight, check_internet
from backend.ai.gemini import GeminiProvider
from backend.ai.service import ChatService
from backend.eventkb import EventManager as EventKnowledgeManager
from backend.eventkb import EventResearcher, EventStore, EventStoreError
from backend.eventkb.storage import MySQLStorage, StorageError
from backend.eventkb.discovery import make_discovery
from backend.eventkb.seed import ensure_first_event
from backend.knowledge.fetch import PoliteFetcher
from backend.knowledge.portal import PortalExtractor, PortalLookup, PortalStorageError
from backend.knowledge.updater import USER_AGENT as KNOWLEDGE_USER_AGENT
from backend.knowledge import KnowledgeBase
from backend.robot.actions import ALLOWED_ACTIONS
from backend.robot.controller import RobotController
from backend.state import StateManager

settings = load_settings()
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
FRONTEND_INDEX = FRONTEND_DIR / "index.html"
logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("senac_bot")

events = EventManager()
state_manager = StateManager()
controller = RobotController(SimulatedHardware(), state_manager, events)

if settings.robot_mode == "physical":
    try:
        controller.set_hardware_mode("physical")
    except RobotError:
        logger.warning("ROBOT_MODE=physical indisponível; iniciando no simulador.")

PROJECT_ROOT = Path(__file__).parent.parent
KNOWLEDGE_DIR = Path(settings.knowledge_dir)
if not KNOWLEDGE_DIR.is_absolute():
    KNOWLEDGE_DIR = PROJECT_ROOT / KNOWLEDGE_DIR
knowledge_base = KnowledgeBase.load(KNOWLEDGE_DIR)

ai_provider = GeminiProvider(
    api_key=settings.gemini_api_key,
    model=settings.gemini_model,
    timeout_seconds=settings.gemini_timeout_seconds,
    max_retries=settings.gemini_max_retries,
)

# Gerenciador de Eventos (camada 2): um evento ativo por instância; os dados de cada evento ficam em events/<id>/.
EVENTS_DIR = Path(settings.events_dir)
if not EVENTS_DIR.is_absolute():
    EVENTS_DIR = PROJECT_ROOT / EVENTS_DIR
EVENT_USER_AGENT = "SENAC-BOT-EventResearch/1.0 (projeto educacional Senac Paraiba; leitura de paginas publicas)"  # ASCII: cabecalho HTTP


def _make_mysql_storage() -> MySQLStorage | None:
    """MySQL quando DB_HOST/DB_NAME/DB_USER estão configurados; senão None (arquivos locais). Um só armazenamento para
    os eventos e para a extração do portal de cursos."""
    if settings.db_host and settings.db_name and settings.db_user:
        try:
            storage = MySQLStorage(
                settings.db_host, settings.db_port, settings.db_name, settings.db_user,
                settings.db_password, settings.db_charset, settings.db_ssl,
            )
            logger.info("Armazenamento em MySQL (%s): eventos e programação de cursos.", settings.db_name)
            return storage
        except StorageError:
            logger.error("MySQL indisponível na inicialização; eventos e programação usarão arquivos locais (NÃO persistentes no Render).")
    return None


mysql_storage = _make_mysql_storage()


def _make_event_store() -> EventStore:
    return EventStore(EVENTS_DIR, mysql_storage) if mysql_storage is not None else EventStore(EVENTS_DIR)


event_store = _make_event_store()
event_manager = EventKnowledgeManager(
    event_store,
    EventResearcher(event_store, lambda: PoliteFetcher(EVENT_USER_AGENT), discovery=make_discovery(ai_provider)),
    aliases=knowledge_base.aliases,
)
ensure_first_event(event_manager)

# Portal oficial de matrículas (Cursos Técnicos — Senac Paraíba): consulta diária antes das conversas; o chat só lê o cache.
# Com MySQL, a extração e as decisões do operador sobrevivem a reinícios/deploys do Render (o arquivo versionado é só a semente).
portal_extractor = PortalExtractor(KNOWLEDGE_DIR, knowledge_base, lambda: PoliteFetcher(KNOWLEDGE_USER_AGENT), storage=mysql_storage)

chat_service = ChatService(
    ai_provider,
    portal=PortalLookup(portal_extractor.store, knowledge_base),
    knowledge=knowledge_base,
    secrets=(settings.gemini_api_key or "",),  # a chave jamais pode aparecer em uma resposta
    events=event_manager,
    external_search=settings.event_external_search,
)


async def _scheduler() -> None:
    """Atualização em segundo plano: roda uma vez ao iniciar e depois a cada 5 min, sem bloquear a aplicação.

    Programação de cursos (portal oficial): baixa de novo só se a última consulta não foi hoje (ver
    PortalExtractor.refresh_if_stale). Eventos: respeita o intervalo configurado em cada evento, quando habilitado.
    """
    while True:
        try:
            await asyncio.to_thread(portal_extractor.refresh_if_stale)
        except Exception:  # noqa: BLE001 - o agendador nunca derruba a aplicação
            logger.exception("Falha na atualização diária do portal de cursos técnicos.")
        if settings.event_auto_update:
            try:
                await asyncio.to_thread(event_manager.run_due_updates)
            except Exception:  # noqa: BLE001 - o agendador nunca derruba a aplicação
                logger.exception("Falha na atualização programada de eventos.")
        await asyncio.sleep(300)


@asynccontextmanager
async def lifespan(_: FastAPI):
    task = asyncio.create_task(_scheduler())
    yield
    task.cancel()


app = FastAPI(title="SENAC BOT", lifespan=lifespan)
register_error_handlers(app)


@app.exception_handler(EventStoreError)
async def event_store_error_handler(_, exc: EventStoreError):
    from fastapi.responses import JSONResponse  # noqa: PLC0415
    return JSONResponse(status_code=exc.status, content={"detail": exc.message})
app.mount("/assets", StaticFiles(directory=FRONTEND_DIR), name="assets")


class ChatRequest(BaseModel):
    message: str = Field(max_length=500)
    session_id: str | None = Field(default=None, max_length=64)
    # Localização autorizada do visitante (opcional, só em memória para esta requisição): usada apenas para
    # calcular a unidade mais próxima; nunca persistida nem enviada ao Gemini.
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)


class SimulatorActionRequest(BaseModel):
    action: str
    # "conversation": mudanças automáticas durante o diálogo, que não poluem os eventos do operador.
    origin: Literal["operator", "conversation"] = "operator"

    @field_validator("action")
    @classmethod
    def action_must_be_allowed(cls, value: str) -> str:
        if value not in ALLOWED_ACTIONS:
            raise ValueError(f"Comando não permitido: {value}")
        return value


class HardwareModeRequest(BaseModel):
    mode: Literal["simulation", "physical"]


class SensorRequest(BaseModel):
    distance_cm: int | None = Field(default=None, ge=0, le=200)
    connected: bool | None = None


def _ai_status() -> str:
    return chat_service.ai_status


def _knowledge_summary() -> dict[str, object]:
    kb = chat_service.knowledge
    return kb.summary() if kb is not None else {"loaded": False, "entries": 0}


def _status_snapshot() -> dict[str, object]:
    return {
        "knowledge": _knowledge_summary(),
        "application": "online",
        "app_env": settings.app_env,
        "ai_status": _ai_status(),
        "microphone": "browser",
        "audio_output": "browser",
        **controller.snapshot(),
    }


@app.get("/")
def homepage() -> FileResponse:
    return FileResponse(FRONTEND_INDEX, media_type="text/html")


@app.get("/favicon.ico")
def favicon() -> FileResponse:
    # Alguns navegadores pedem /favicon.ico na raiz mesmo havendo <link rel="icon"> no HTML.
    return FileResponse(FRONTEND_DIR / "brand" / "favicon.ico", media_type="image/x-icon")


@app.get("/health")
def health() -> dict[str, object]:
    ai_status = _ai_status()
    return {
        "status": "ok",
        "ai_status": ai_status,
        "gemini_status": ai_status,
        "gemini_configurado": ai_status != "not_configured",
    }


@app.get("/api/status")
def application_status() -> dict[str, object]:
    return _status_snapshot()


@app.post("/api/session/start")
def start_session() -> dict[str, object]:
    controller.start_session()
    return _status_snapshot()


@app.post("/api/session/stop")
def stop_session() -> dict[str, object]:
    controller.stop_session()
    chat_service.clear_contexts()
    return _status_snapshot()


@app.post("/api/emergency")
def toggle_emergency_stop() -> dict[str, object]:
    controller.toggle_emergency()
    chat_service.clear_contexts()
    return _status_snapshot()


@app.post("/api/simulator/action")
def simulator_action(request: SimulatorActionRequest) -> dict[str, object]:
    controller.execute(request.action, quiet=request.origin == "conversation")
    return _status_snapshot()


@app.post("/api/simulator/sensors")
def simulator_sensors(request: SensorRequest) -> dict[str, object]:
    """Altera os sensores simulados (distância e conexão); o controlador aplica a segurança."""
    controller.update_simulated_sensors(request.distance_cm, request.connected)
    return _status_snapshot()


@app.post("/api/hardware/mode")
def hardware_mode(request: HardwareModeRequest) -> dict[str, object]:
    """Alterna simulador/físico. Se o físico falhar, responde 409 e o simulador continua ativo."""
    controller.set_hardware_mode(request.mode)
    return _status_snapshot()


@app.post("/api/demo/start")
def demo_start() -> dict[str, object]:
    controller.start_demo()
    return _status_snapshot()


@app.post("/api/demo/stop")
def demo_stop() -> dict[str, object]:
    controller.stop_demo()
    return _status_snapshot()


@app.post("/api/preflight")
def preflight() -> dict[str, object]:
    """Verificação de prontidão (internet, Gemini, hardware, emergência). O áudio é verificado no navegador."""
    internet_ok = check_internet()
    if internet_ok:
        chat_service.check_ai()
    snapshot = controller.snapshot()
    snapshot["knowledge"] = _knowledge_summary()
    return build_preflight(internet_ok, chat_service.ai_status, snapshot)


@app.websocket("/ws/status")
async def status_socket(websocket: WebSocket) -> None:
    """Envia o estado completo sempre que ele muda (substitui o polling do navegador)."""
    await websocket.accept()
    last: dict[str, object] | None = None
    try:
        while True:
            snapshot = _status_snapshot()
            if snapshot != last:
                await websocket.send_json(snapshot)
                last = snapshot
            try:  # também detecta a desconexão do cliente
                await asyncio.wait_for(websocket.receive_text(), timeout=0.25)
            except asyncio.TimeoutError:
                pass
    except WebSocketDisconnect:
        logger.debug("Cliente WebSocket desconectado.")
    except Exception:  # noqa: BLE001
        logger.exception("Erro no WebSocket de status.")


@app.post("/api/ai/check")
def check_ai() -> dict[str, object]:
    """Verifica chave, modelo e conectividade do Gemini (ação do operador)."""
    chat_service.check_ai()
    return _status_snapshot()


@app.get("/api/knowledge/status")
def knowledge_status() -> dict[str, object]:
    """Estado da base de conhecimento (operador): contagens, itens desatualizados, pendências e saúde das fontes."""
    kb = chat_service.knowledge
    return kb.status() if kb is not None else {"loaded": False, "entries": 0}


@app.get("/api/knowledge/portal")
def knowledge_portal() -> dict[str, object]:
    """Fonte oficial de cursos técnicos: dados extraídos, situação de cada registro e resolução das pendências (operador)."""
    summary = portal_extractor.store.summary()
    source = knowledge_base.sources.get("pb-programacao-cursos")
    summary["source"] = ({"id": source.id, "name": source.name, "url": source.url, "category": source.category, "institution": source.institution,
                          "kind": source.kind, "freshness": source.freshness} if source else None)
    return summary


@app.post("/api/knowledge/portal/refresh")
def refresh_knowledge_portal(payload: dict[str, Any] | None = None) -> dict[str, object]:
    """Consulta de novo a fonte oficial (respeita cache e intervalo mínimo; `force` ignora o cache, não o intervalo do site)."""
    result = portal_extractor.refresh(force=bool((payload or {}).get("force")))
    return {"outcome": result.outcome, "detail": result.detail, "portal": knowledge_portal()}


@app.post("/api/knowledge/portal/records/{record_id}/{decision}")
def decide_portal_record(record_id: str, decision: str) -> dict[str, object]:
    if decision not in ("approve", "reject"):
        raise HTTPException(status_code=404, detail="Decisão inválida.")
    try:
        record = portal_extractor.store.decide(record_id, decision)
    except KeyError:
        raise HTTPException(status_code=404, detail="Registro não encontrado.") from None
    except PortalStorageError as error:
        raise HTTPException(status_code=503, detail=str(error)) from None
    return {"record": record, "portal": knowledge_portal()}


@app.get("/api/knowledge/search")
def knowledge_search(q: str = "") -> dict[str, object]:
    """Consulta direta à base (teste do operador): mostra as entradas encontradas e a situação de cada uma."""
    kb = chat_service.knowledge
    if kb is None or not q.strip():
        return {"query": q, "confident": False, "hits": []}
    result = kb.search(q[:500])
    return {
        "query": q,
        "confident": result.confident,
        "institutional": result.institutional,
        "corporate": result.corporate,
        "unit": result.unit,
        "coverage": round(result.coverage, 2),
        "hits": [
            {"id": h.entry.id, "title": h.entry.title, "score": round(h.score, 1), "status": kb.effective(h.entry),
             "level": h.entry.level, "unit": h.entry.unit, "category": h.entry.category}
            for h in result.hits
        ],
    }


# ---------------------------------------------------------------- Gerenciador de Eventos
@app.get("/api/event/active")
def active_event() -> dict[str, object]:
    """Público: apenas o que o visitante pode ver do evento ativo (nome, tema, boas-vindas e sugestões)."""
    return event_manager.public_info()


@app.get("/api/events")
def list_events() -> dict[str, object]:
    return {"events": event_manager.list_events(), "active_id": event_store.active_id(), "job": event_manager.job_status()}


@app.post("/api/events")
def create_event(payload: dict[str, Any]) -> dict[str, object]:
    return event_manager.create(payload)


@app.get("/api/events/job")
def event_job() -> dict[str, object]:
    return event_manager.job_status()


@app.post("/api/events/deactivate")
def deactivate_event() -> dict[str, object]:
    chat_service.clear_contexts()
    return {"event": event_manager.deactivate()}


@app.post("/api/events/{event_id}/approve-pending")
def approve_pending(event_id: str) -> dict[str, object]:
    return {"approved": event_manager.approve_all_pending(event_id)}


@app.get("/api/events/{event_id}")
def event_detail(event_id: str) -> dict[str, object]:
    return event_manager.detail(event_id)


@app.put("/api/events/{event_id}")
def update_event(event_id: str, payload: dict[str, Any]) -> dict[str, object]:
    return event_manager.update(event_id, payload)


@app.post("/api/events/{event_id}/research")
def research_event(event_id: str, payload: dict[str, Any] | None = None) -> dict[str, object]:
    mode = (payload or {}).get("mode", "prepare")
    return event_manager.start_research(event_id, "update" if mode == "update" else "prepare")


@app.post("/api/events/{event_id}/activate")
def activate_event(event_id: str) -> dict[str, object]:
    chat_service.clear_contexts()  # a conversa em andamento não carrega o contexto do evento anterior
    return {"event": event_manager.activate(event_id)}


@app.post("/api/events/{event_id}/archive")
def archive_event(event_id: str) -> dict[str, object]:
    chat_service.clear_contexts()
    return {"event": event_manager.archive(event_id)}


@app.post("/api/events/{event_id}/unarchive")
def unarchive_event(event_id: str) -> dict[str, object]:
    return {"event": event_manager.unarchive(event_id)}


@app.post("/api/events/{event_id}/sources")
def add_event_source(event_id: str, payload: dict[str, Any]) -> dict[str, object]:
    return event_manager.add_source(event_id, str(payload.get("url", "")).strip(), str(payload.get("kind", "other")), str(payload.get("trust", "official")))


@app.patch("/api/events/{event_id}/sources/{source_id}")
def set_event_source_trust(event_id: str, source_id: str, payload: dict[str, Any]) -> dict[str, object]:
    return event_manager.set_source_trust(event_id, source_id, str(payload.get("trust", "")))


@app.delete("/api/events/{event_id}/sources/{source_id}")
def remove_event_source(event_id: str, source_id: str) -> dict[str, object]:
    event_manager.remove_source(event_id, source_id)
    return {"removed": source_id}


@app.post("/api/events/{event_id}/items")
def add_event_item(event_id: str, payload: dict[str, Any]) -> dict[str, object]:
    return event_manager.add_item(event_id, str(payload.get("category", "")), str(payload.get("title", "")), str(payload.get("content", "")))


@app.post("/api/events/{event_id}/items/{item_id}/approve")
def approve_event_item(event_id: str, item_id: str) -> dict[str, object]:
    return event_manager.approve(event_id, item_id)


@app.post("/api/events/{event_id}/items/{item_id}/reject")
def reject_event_item(event_id: str, item_id: str, payload: dict[str, Any] | None = None) -> dict[str, object]:
    return event_manager.reject(event_id, item_id, str((payload or {}).get("reason", "")))


@app.put("/api/events/{event_id}/items/{item_id}")
def edit_event_item(event_id: str, item_id: str, payload: dict[str, Any]) -> dict[str, object]:
    return event_manager.edit_item(event_id, item_id, payload.get("content"), payload.get("title"), payload.get("category"))


@app.post("/chat")
def chat(request: ChatRequest) -> dict[str, object]:
    message = request.message.strip()
    if not message:
        raise HTTPException(status_code=422, detail="A mensagem não pode estar vazia.")
    controller.assert_not_stopped()
    reply = chat_service.reply(request.session_id, message, lat=request.lat, lon=request.lon)
    controller.note_chat_reply(reply.source)
    controller.react_to_chat(reply.intent)
    return {
        "response": reply.text,
        "source": reply.source,
        "reason": reply.reason or "",
        "intent": reply.intent or "",
        "knowledge": list(reply.knowledge),
        "links": [{"label": link.label, "url": link.url} for link in reply.links],
    }
