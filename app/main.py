import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes_auth import router as auth_router
from app.api.routes_connections import router as connections_router
from app.api.routes_history import router as history_router
from app.api.routes_live_ws import router as live_ws_router
from app.api.routes_tags import router as tags_router
from app.config import get_settings
from app.connectors.base import Sample
from app.core.security import ensure_default_admin
from app.core.supervisor import ConnectorSupervisor
from app.db.bootstrap import init_db
from app.ingest.pipeline import IngestPipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("ackiologs")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    import os

    os.makedirs("data", exist_ok=True)

    await init_db()
    await ensure_default_admin()

    queue: asyncio.Queue[Sample] = asyncio.Queue(maxsize=settings.ingest_queue_maxsize)
    supervisor = ConnectorSupervisor(queue)
    pipeline = IngestPipeline(queue)

    app.state.supervisor = supervisor
    app.state.pipeline = pipeline

    await supervisor.load_and_sync()
    pipeline_task = asyncio.create_task(pipeline.run())
    await pipeline.load_metadata()  # ensure metadata is loaded before connectors start emitting
    await supervisor.start_all()

    logger.info("Ackiologs historian started: %d connection(s), %d tag(s)", len(supervisor.config.connections), len(supervisor.config.tags))

    try:
        yield
    finally:
        await supervisor.stop_all()
        await pipeline.stop()
        pipeline_task.cancel()
        await asyncio.gather(pipeline_task, return_exceptions=True)


app = FastAPI(title="Ackiologs Industrial Historian", version="0.1.0", lifespan=lifespan)

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


@app.get("/health")
async def health():
    return {"status": "ok"}


app.mount("/", StaticFiles(directory="app/web/static", html=True), name="web")
