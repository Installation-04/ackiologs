from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import CurrentUser, get_current_user
from app.db.base import get_session
from app.db.models import Tag, TagValue

router = APIRouter(prefix="/api/history", tags=["history"])


@router.get("/{tag_name}")
async def get_history(
    tag_name: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[CurrentUser, Depends(get_current_user)],
    start: datetime | None = None,
    end: datetime | None = None,
    interval_seconds: Annotated[int, Query(ge=0, description="0 = raw samples, >0 = time-bucketed average")] = 0,
    limit: Annotated[int, Query(le=50_000)] = 5_000,
):
    tag = (await session.execute(select(Tag).where(Tag.name == tag_name))).scalar_one_or_none()
    if tag is None:
        raise HTTPException(status_code=404, detail="tag not found")

    end = end or datetime.now(timezone.utc)
    start = start or (end - timedelta(hours=1))

    if interval_seconds > 0:
        return await _bucketed(session, tag, start, end, interval_seconds, limit)
    return await _raw(session, tag, start, end, limit)


async def _raw(session: AsyncSession, tag: Tag, start: datetime, end: datetime, limit: int):
    stmt = (
        select(TagValue)
        .where(TagValue.tag_id == tag.id, TagValue.ts >= start, TagValue.ts <= end)
        .order_by(TagValue.ts)
        .limit(limit)
    )
    rows = (await session.execute(stmt)).scalars().all()
    return {
        "tag": tag.name,
        "mode": "raw",
        "points": [
            {"ts": r.ts.isoformat(), "value": _value_of(r), "quality": r.quality.value} for r in rows
        ],
    }


async def _bucketed(session: AsyncSession, tag: Tag, start: datetime, end: datetime, interval_seconds: int, limit: int):
    # Portable time-bucketing (works on SQLite and Postgres alike) via epoch-second math;
    # on Postgres/Timescale this can be swapped for time_bucket() for better performance.
    epoch = func.extract("epoch", TagValue.ts)
    bucket = (func.floor(epoch / interval_seconds) * interval_seconds).label("bucket")
    stmt = (
        select(bucket, func.avg(TagValue.value_float), func.min(TagValue.value_float), func.max(TagValue.value_float), func.count())
        .where(TagValue.tag_id == tag.id, TagValue.ts >= start, TagValue.ts <= end)
        .group_by(bucket)
        .order_by(bucket)
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    return {
        "tag": tag.name,
        "mode": "bucketed",
        "interval_seconds": interval_seconds,
        "points": [
            {
                # Postgres returns EXTRACT(epoch ...) as decimal.Decimal, not a float
                # like SQLite does — fromtimestamp() rejects Decimal, so cast explicitly.
                "ts": datetime.fromtimestamp(float(b), tz=timezone.utc).isoformat(),
                "avg": float(avg) if avg is not None else None,
                "min": float(mn) if mn is not None else None,
                "max": float(mx) if mx is not None else None,
                "count": cnt,
            }
            for b, avg, mn, mx, cnt in rows
        ],
    }


def _value_of(r: TagValue):
    if r.value_float is not None:
        return r.value_float
    if r.value_bool is not None:
        return r.value_bool
    return r.value_string
