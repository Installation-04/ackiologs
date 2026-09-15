from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import CurrentUser, Role, get_current_user, require_role
from app.db.base import get_session
from app.db.models import AlarmDefinition, AlarmEvent, AlarmState, Tag

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


@router.get("/history")
async def alarm_history(
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[CurrentUser, Depends(get_current_user)],
    start: datetime | None = None,
    end: datetime | None = None,
    tag_name: str | None = None,
    state: str | None = None,
    priority: int | None = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """Searchable, paginated alarm & event journal for the dashboard's Alarm
    History page — distinct from GET /events, which just shows the most recent
    activity. Every filter is optional; combine start/end, tag, state, and
    alarm priority (from the alarm's definition, not the event) to narrow down
    a specific incident. Returns one extra row over `limit` when there's a
    next page, so the dashboard can page without a separate COUNT(*) query."""
    if state is not None and state not in AlarmState.__members__.values():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"state must be one of {[s.value for s in AlarmState]}",
        )

    stmt = (
        select(AlarmEvent, Tag.name, AlarmDefinition.name, AlarmDefinition.condition, AlarmDefinition.priority)
        .join(Tag, Tag.id == AlarmEvent.tag_id, isouter=True)
        .join(AlarmDefinition, AlarmDefinition.id == AlarmEvent.alarm_id, isouter=True)
    )
    if start is not None:
        stmt = stmt.where(AlarmEvent.ts >= start)
    if end is not None:
        stmt = stmt.where(AlarmEvent.ts <= end)
    if tag_name is not None:
        stmt = stmt.where(Tag.name == tag_name)
    if state is not None:
        stmt = stmt.where(AlarmEvent.state == AlarmState(state))
    if priority is not None:
        stmt = stmt.where(AlarmDefinition.priority == priority)

    stmt = stmt.order_by(AlarmEvent.ts.desc()).offset(offset).limit(limit + 1)
    rows = (await session.execute(stmt)).all()
    has_more = len(rows) > limit
    rows = rows[:limit]

    return {
        "events": [
            {
                "id": e.id,
                "alarm_id": e.alarm_id,
                "alarm_name": alarm_name,
                "condition": condition.value if condition is not None else None,
                "priority": alarm_priority,
                "tag_id": e.tag_id,
                "tag_name": tag_name_,
                "ts": e.ts.isoformat(),
                "state": e.state.value,
                "value": e.value,
                "message": e.message,
                "acked_by": e.acked_by,
            }
            for e, tag_name_, alarm_name, condition, alarm_priority in rows
        ],
        "offset": offset,
        "limit": limit,
        "has_more": has_more,
    }


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
