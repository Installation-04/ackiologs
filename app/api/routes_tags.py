from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import CurrentUser, get_current_user
from app.db.base import get_session
from app.db.models import AlarmDefinition, Tag
from app.ingest.live import live_bus

router = APIRouter(prefix="/api/tags", tags=["tags"])


@router.get("")
async def list_tags(
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[CurrentUser, Depends(get_current_user)],
):
    tags = (await session.execute(select(Tag).order_by(Tag.name))).scalars().all()
    snapshot = live_bus.snapshot()
    result = []
    for t in tags:
        live = snapshot.get(t.name)
        result.append(
            {
                "id": t.id,
                "name": t.name,
                "description": t.description,
                "connection": t.connection_name,
                "address": t.address,
                "data_type": t.data_type.value,
                "engineering_units": t.engineering_units,
                "min_value": t.min_value,
                "max_value": t.max_value,
                "archive_enabled": t.archive_enabled,
                "live_value": live.value if live else None,
                "live_ts": live.ts.isoformat() if live else None,
                "live_quality": live.quality if live else None,
            }
        )
    return result


@router.get("/{tag_name}")
async def get_tag(
    tag_name: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[CurrentUser, Depends(get_current_user)],
):
    tag = (await session.execute(select(Tag).where(Tag.name == tag_name))).scalar_one_or_none()
    if tag is None:
        raise HTTPException(status_code=404, detail="tag not found")
    alarms = (await session.execute(select(AlarmDefinition).where(AlarmDefinition.tag_id == tag.id))).scalars().all()
    live = live_bus.snapshot().get(tag.name)
    return {
        "id": tag.id,
        "name": tag.name,
        "description": tag.description,
        "connection": tag.connection_name,
        "address": tag.address,
        "data_type": tag.data_type.value,
        "engineering_units": tag.engineering_units,
        "min_value": tag.min_value,
        "max_value": tag.max_value,
        "deadband_percent": tag.deadband_percent,
        "archive_enabled": tag.archive_enabled,
        "live_value": live.value if live else None,
        "live_ts": live.ts.isoformat() if live else None,
        "alarms": [
            {"id": a.id, "name": a.name, "condition": a.condition.value, "setpoint": a.setpoint, "priority": a.priority, "enabled": a.enabled}
            for a in alarms
        ],
    }
