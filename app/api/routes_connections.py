from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_supervisor
from app.core.security import CurrentUser, get_current_user, require_role
from app.core.supervisor import ConnectorSupervisor
from app.db.base import get_session
from app.db.models import AlarmEvent, Role

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
    await supervisor.write_tag(tag_name, body.value)
    return {"status": "ok"}


@router.get("/alarms/events")
async def alarm_events(
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[CurrentUser, Depends(get_current_user)],
    limit: int = 200,
):
    rows = (await session.execute(select(AlarmEvent).order_by(AlarmEvent.ts.desc()).limit(limit))).scalars().all()
    return [
        {
            "id": e.id,
            "alarm_id": e.alarm_id,
            "tag_id": e.tag_id,
            "ts": e.ts.isoformat(),
            "state": e.state.value,
            "value": e.value,
            "message": e.message,
        }
        for e in rows
    ]


@router.post("/config/reload")
async def reload_config(
    supervisor: Annotated[ConnectorSupervisor, Depends(get_supervisor)],
    _user: Annotated[CurrentUser, Depends(require_role(Role.ADMIN))],
):
    """Re-read config/tags.yaml and config/connections.yaml and upsert tags/alarms.
    New connections require a restart; tag/alarm edits take effect immediately."""
    await supervisor.load_and_sync()
    return {"status": "reloaded", "tags": len(supervisor.config.tags), "connections": len(supervisor.config.connections)}
