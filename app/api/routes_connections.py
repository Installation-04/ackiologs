from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.api.deps import get_pipeline, get_supervisor
from app.core.security import CurrentUser, get_current_user, require_role
from app.core.supervisor import ConnectorSupervisor
from app.db.models import Role
from app.ingest.pipeline import IngestPipeline

router = APIRouter(prefix="/api", tags=["connections"])


@router.get("/connections")
async def list_connections(
    supervisor: Annotated[ConnectorSupervisor, Depends(get_supervisor)],
    _user: Annotated[CurrentUser, Depends(get_current_user)],
):
    return supervisor.health()


class WriteRequest(BaseModel):
    value: Any


@router.post("/tags/{tag_name}/write")
async def write_tag(
    tag_name: str,
    body: WriteRequest,
    supervisor: Annotated[ConnectorSupervisor, Depends(get_supervisor)],
    _user: Annotated[CurrentUser, Depends(require_role(Role.OPERATOR, Role.ADMIN))],
):
    try:
        await supervisor.write_tag(tag_name, body.value)
    except (ValueError, NotImplementedError) as exc:
        # unknown tag, or the connector doesn't support writes (e.g. the Simulator) —
        # a client-fixable request error, not a server fault.
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"status": "ok"}


@router.post("/config/reload")
async def reload_config(
    supervisor: Annotated[ConnectorSupervisor, Depends(get_supervisor)],
    pipeline: Annotated[IngestPipeline, Depends(get_pipeline)],
    _user: Annotated[CurrentUser, Depends(require_role(Role.ADMIN))],
):
    """Re-read config/tags.yaml and config/connections.yaml and upsert tags/alarms.
    New connections require a restart; tag/alarm edits (deadband, alarm setpoints,
    engineering range, etc.) take effect immediately — the running ingest pipeline's
    in-memory metadata is refreshed here too, not just the database."""
    await supervisor.load_and_sync()
    await pipeline.load_metadata()

    from app.core.modbus_server import embedded_modbus_server
    from app.core.opcua_server import embedded_opcua_server

    if embedded_opcua_server.running:
        await embedded_opcua_server.restart()
    if embedded_modbus_server.running:
        await embedded_modbus_server.restart()

    return {"status": "reloaded", "tags": len(supervisor.config.tags), "connections": len(supervisor.config.connections)}
