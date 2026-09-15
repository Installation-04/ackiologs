"""The ingestion pipeline: connectors -> asyncio.Queue -> [deadband filter ->
live bus update -> alarm evaluation -> batched DB write]. One consumer task
drains the shared queue so all connectors share a single, bounded backpressure
point and the DB only ever sees batched, size-bounded writes."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.config import get_settings
from app.connectors.base import Sample
from app.core.runtime_settings import runtime_settings
from app.db.base import session_scope
from app.db.models import AlarmCondition, AlarmDefinition, AlarmEvent, AlarmState, DataType, Quality, Tag, TagValue
from app.ingest.live import LiveValue, live_bus

logger = logging.getLogger("ackiologs.ingest")


@dataclass
class TagMeta:
    id: int
    data_type: DataType
    min_value: float | None
    max_value: float | None
    deadband_percent: float | None
    archive_enabled: bool


@dataclass
class AlarmRuntimeState:
    definition: AlarmDefinition
    active: bool = False


class IngestPipeline:
    def __init__(self, queue: asyncio.Queue[Sample]) -> None:
        self.queue = queue
        self.settings = get_settings()
        self._tag_meta: dict[str, TagMeta] = {}
        self._last_value: dict[str, Any] = {}
        self._alarms_by_tag: dict[str, list[AlarmRuntimeState]] = {}
        self._buffer: list[TagValue] = []
        self._stop = asyncio.Event()

    async def load_metadata(self) -> None:
        """(Re-)load tag and alarm definitions from the DB. Safe to call again after
        `POST /api/config/reload` has synced edited config into the DB — an already-
        ACTIVE alarm's state is preserved across the reload so it isn't reported as a
        fresh activation on the next sample."""
        previously_active = {
            state.definition.id for states in self._alarms_by_tag.values() for state in states if state.active
        }
        async with session_scope() as session:
            tags = (await session.execute(select(Tag))).scalars().all()
            self._tag_meta = {
                t.name: TagMeta(t.id, t.data_type, t.min_value, t.max_value, t.deadband_percent, t.archive_enabled)
                for t in tags
            }
            alarms = (await session.execute(select(AlarmDefinition).where(AlarmDefinition.enabled == True))).scalars().all()  # noqa: E712
            by_id = {t.id: t.name for t in tags}
            self._alarms_by_tag = {}
            for a in alarms:
                tag_name = by_id.get(a.tag_id)
                if not tag_name:
                    continue
                state = AlarmRuntimeState(a, active=a.id in previously_active)
                self._alarms_by_tag.setdefault(tag_name, []).append(state)

    async def run(self) -> None:
        await self.load_metadata()
        flush_task = asyncio.create_task(self._periodic_flush())
        try:
            while not self._stop.is_set():
                try:
                    sample = await asyncio.wait_for(self.queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                await self._handle_sample(sample)
                if len(self._buffer) >= self.settings.ingest_batch_size:
                    await self._flush()
        finally:
            flush_task.cancel()
            await self._flush()

    async def stop(self) -> None:
        self._stop.set()

    async def _periodic_flush(self) -> None:
        while True:
            await asyncio.sleep(self.settings.ingest_flush_interval_seconds)
            await self._flush()

    async def _handle_sample(self, sample: Sample) -> None:
        meta = self._tag_meta.get(sample.tag_name)
        if meta is None:
            logger.debug("sample for unknown tag %s dropped (not in config)", sample.tag_name)
            return

        value_float, value_string, value_bool = self._coerce(sample.value, meta.data_type)

        live_bus.update(LiveValue(sample.tag_name, sample.value, sample.ts, sample.quality))
        await self._evaluate_alarms(sample.tag_name, meta, value_float, sample)

        if not meta.archive_enabled:
            return
        if self._within_deadband(sample.tag_name, meta, value_float):
            return

        self._last_value[sample.tag_name] = value_float if value_float is not None else sample.value
        self._buffer.append(
            TagValue(
                tag_id=meta.id,
                ts=sample.ts,
                value_float=value_float,
                value_string=value_string,
                value_bool=value_bool,
                quality=Quality(sample.quality) if sample.quality in Quality.__members__.values() else Quality.GOOD,
            )
        )

    def _within_deadband(self, tag_name: str, meta: TagMeta, value_float: float | None) -> bool:
        if value_float is None or meta.min_value is None or meta.max_value is None:
            return False
        deadband_pct = (
            meta.deadband_percent
            if meta.deadband_percent is not None
            else runtime_settings.get("retention.default_deadband_percent")
        )
        if not deadband_pct:
            return False
        last = self._last_value.get(tag_name)
        if last is None:
            return False
        span = meta.max_value - meta.min_value
        if span <= 0:
            return False
        threshold = span * (deadband_pct / 100.0)
        return abs(value_float - last) < threshold

    @staticmethod
    def _coerce(value: Any, data_type: DataType) -> tuple[float | None, str | None, bool | None]:
        if value is None:
            return None, None, None
        try:
            if data_type == DataType.FLOAT:
                return float(value), None, None
            if data_type == DataType.INT:
                return float(int(value)), None, None
            if data_type == DataType.BOOL:
                return None, None, bool(value)
            return None, str(value), None
        except (TypeError, ValueError):
            return None, str(value), None

    async def _evaluate_alarms(self, tag_name: str, meta: TagMeta, value_float: float | None, sample: Sample) -> None:
        states = self._alarms_by_tag.get(tag_name)
        if not states:
            return
        for state in states:
            a = state.definition
            should_be_active = self._alarm_condition_met(a, value_float, sample)
            if should_be_active and not state.active:
                state.active = True
                await self._write_alarm_event(a, tag_name, AlarmState.ACTIVE, value_float)
            elif not should_be_active and state.active:
                state.active = False
                await self._write_alarm_event(a, tag_name, AlarmState.CLEARED, value_float)

    @staticmethod
    def _alarm_condition_met(a: AlarmDefinition, value_float: float | None, sample: Sample) -> bool:
        if a.condition == AlarmCondition.BAD_QUALITY:
            return sample.quality == "bad"
        if value_float is None:
            return False
        if a.setpoint is None:
            return False
        if a.condition == AlarmCondition.HIGH:
            return value_float > a.setpoint
        if a.condition == AlarmCondition.HIGH_HIGH:
            return value_float > a.setpoint
        if a.condition == AlarmCondition.LOW:
            return value_float < a.setpoint
        if a.condition == AlarmCondition.LOW_LOW:
            return value_float < a.setpoint
        if a.condition == AlarmCondition.DIGITAL_TRUE:
            return bool(value_float)
        if a.condition == AlarmCondition.DIGITAL_FALSE:
            return not bool(value_float)
        return False

    async def _write_alarm_event(self, a: AlarmDefinition, tag_name: str, state: AlarmState, value: float | None) -> None:
        async with session_scope() as session:
            session.add(
                AlarmEvent(
                    alarm_id=a.id,
                    tag_id=a.tag_id,
                    ts=datetime.now(timezone.utc),
                    state=state,
                    value=value,
                    message=a.message or f"{tag_name} {a.condition.value} {state.value}",
                )
            )
            await session.commit()
        logger.info("ALARM %s: %s %s (value=%s)", state.value.upper(), tag_name, a.condition.value, value)

    async def _flush(self) -> None:
        if not self._buffer:
            return
        batch, self._buffer = self._buffer, []
        async with session_scope() as session:
            session.add_all(batch)
            await session.commit()
