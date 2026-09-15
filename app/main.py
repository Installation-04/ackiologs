import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes_alarms import router as alarms_router
from app.api.routes_auth import router as auth_router
from app.api.routes_connections import router as connections_router
from app.api.routes_history import router as history_router
from app.api.routes_live_ws import router as live_ws_router
from app.api.routes_settings import router as settings_router
from app.api.routes_tags import router as tags_router
from app._version import __version__
from app.config import get_settings
from app.connectors.base import Sample
from app.core.opcua_server import embedded_opcua_server
from app.core.runtime_settings import runtime_settings
from app.core.security import ensure_default_admin
from app.core.supervisor import ConnectorSupervisor
from app.db.bootstrap import init_db
from app.ingest.pipeline import IngestPipeline
from app.ingest.retention import run_retention_pruner
from app.paths import bundled_static_dir, default_data_dir, sqlite_file_path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("ackiologs")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    sqlite_path = sqlite_file_path(settings.database_url)
    (sqlite_path.parent if sqlite_path else default_data_dir()).mkdir(parents=True, exist_ok=True)

    await init_db()
    await ensure_default_admin()
    await runtime_settings.load(
        seed={
            "general.site_name": settings.app_name,
            "retention.days": settings.retention_days,
            "retention.default_deadband_percent": settings.default_deadband_percent,
            "security.access_token_expire_minutes": settings.access_token_expire_minutes,
        }
    )

    queue: asyncio.Queue[Sample] = asyncio.Queue(maxsize=settings.ingest_queue_maxsize)
    supervisor = ConnectorSupervisor(queue)
    pipeline = IngestPipeline(queue)

    app.state.supervisor = supervisor
    app.state.pipeline = pipeline

    await supervisor.load_and_sync()
    pipeline_task = asyncio.create_task(pipeline.run())
    await pipeline.load_metadata()  # ensure metadata is loaded before connectors start emitting
    await supervisor.start_all()

    retention_stop = asyncio.Event()
    retention_task = asyncio.create_task(run_retention_pruner(retention_stop))

    if runtime_settings.get("opcua_server.enabled"):
        await embedded_opcua_server.start()

    logger.info("Ackiologs historian started: %d connection(s), %d tag(s)", len(supervisor.config.connections), len(supervisor.config.tags))

    try:
        yield
    finally:
        await embedded_opcua_server.stop()
        retention_stop.set()
        retention_task.cancel()
        await asyncio.gather(retention_task, return_exceptions=True)
        await supervisor.stop_all()
        await pipeline.stop()
        pipeline_task.cancel()
        await asyncio.gather(pipeline_task, return_exceptions=True)


app = FastAPI(title="Ackiologs Industrial Historian", version=__version__, lifespan=lifespan)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(tags_router)
app.include_router(history_router)
app.include_router(connections_router)
app.include_router(live_ws_router)
app.include_router(alarms_router)
app.include_router(settings_router)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/api/version")
async def version():
    return {"version": __version__}


app.mount("/", StaticFiles(directory=str(bundled_static_dir()), html=True), name="web")
