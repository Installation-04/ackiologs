from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import CurrentUser, Role, get_current_user, require_role
from app.db.base import get_session
from app.db.models import AlarmEvent, AlarmState, Tag

router = APIRouter(prefix="/api/alarms", tags=["alarms"])


@router.get("/events")
async def alarm_events(
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[CurrentUser, Depends(get_current_user)],
    limit: int = 200,
):
    stmt = (
        select(AlarmEvent, Tag.name)
        .join(Tag, Tag.id == AlarmEvent.tag_id, isouter=True)
        .order_by(AlarmEvent.ts.desc())
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    return [
        {
            "id": e.id,
            "alarm_id": e.alarm_id,
            "tag_id": e.tag_id,
            "tag_name": tag_name,
            "ts": e.ts.isoformat(),
            "state": e.state.value,
            "value": e.value,
            "message": e.message,
            "acked_by": e.acked_by,
        }
        for e, tag_name in rows
    ]


@router.post("/events/{alarm_id}/ack")
async def acknowledge_alarm(
    alarm_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[CurrentUser, Depends(require_role(Role.OPERATOR, Role.ADMIN))],
):
    """Record an operator acknowledgment (ISA-18.2 style) as a new journal entry —
    the alarm & event log stays an append-only history, so this never rewrites a
    past ACTIVE/CLEARED row. Acks the alarm *definition* (its most recent event),
    not one specific historical event row."""
    latest = (
        await session.execute(
            select(AlarmEvent).where(AlarmEvent.alarm_id == alarm_id).order_by(AlarmEvent.ts.desc()).limit(1)
        )
    ).scalar_one_or_none()
    if latest is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no events for this alarm")

    session.add(
        AlarmEvent(
            alarm_id=latest.alarm_id,
            tag_id=latest.tag_id,
            state=AlarmState.ACKED,
            value=latest.value,
            message=latest.message,
            acked_by=user.username,
        )
    )
    await session.commit()
    return {"status": "acked", "alarm_id": alarm_id, "acked_by": user.username}
