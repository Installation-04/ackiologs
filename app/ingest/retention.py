"""Background history pruning — deletes tag_values older than the "History
retention (days)" setting. Runs on any backend (SQLite, plain Postgres,
TimescaleDB): TimescaleDB's own chunk-dropping retention policy would be more
I/O-efficient at very large scale, but a plain DELETE is correct everywhere
and, critically, lets retention be changed live from the Settings page
without touching the database directly. See app/db/bootstrap.py for why the
Timescale-native policy isn't used instead."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete

from app.core.runtime_settings import runtime_settings
from app.db.base import session_scope
from app.db.models import TagValue

logger = logging.getLogger("ackiologs.retention")

CHECK_INTERVAL_SECONDS = 3600


async def run_retention_pruner(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            await _prune_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("retention pruning pass failed")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=CHECK_INTERVAL_SECONDS)
        except asyncio.TimeoutError:
            pass


async def _prune_once() -> None:
    days = runtime_settings.get("retention.days")
    if not days or days <= 0:
        return
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    async with session_scope() as session:
        result = await session.execute(delete(TagValue).where(TagValue.ts < cutoff))
        await session.commit()
        deleted = result.rowcount or 0
    if deleted:
        logger.info("retention: pruned %d sample(s) older than %d day(s)", deleted, days)
