"""Owns the lifecycle of every configured connector: syncs config/*.yaml into the
`tags` table, starts one asyncio task per connection, restarts crashed connectors
with backoff, and exposes health for the API/dashboard."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.config import get_settings
from app.connectors.base import BaseConnector, Sample
from app.connectors.registry import get_connector_class
from app.core.config_loader import HistorianConfig, load_config, tag_spec_to_connector_dict
from app.db.base import session_scope
from app.db.models import AlarmCondition, AlarmDefinition, ConnectionStatusLog, DataType, Tag

logger = logging.getLogger("ackiologs.supervisor")


class ConnectorSupervisor:
    def __init__(self, queue: asyncio.Queue[Sample]) -> None:
        self.queue = queue
        self.settings = get_settings()
        self.config: HistorianConfig | None = None
        self._connectors: dict[str, BaseConnector] = {}
        self._tasks: dict[str, asyncio.Task] = {}

    async def load_and_sync(self) -> None:
        self.config = load_config(self.settings.connections_config_path, self.settings.tags_config_path)
        await self._sync_tags_to_db(self.config)

    async def start_all(self) -> None:
        if self.config is None:
            await self.load_and_sync()
        for conn_spec in self.config.connections:
            self._start_connection(conn_spec)

    def _start_connection(self, conn_spec) -> None:
        connector_cls = get_connector_class(conn_spec.protocol)
        tag_specs = self.config.tags_by_connection(conn_spec.name)
        tag_dicts = [tag_spec_to_connector_dict(t) for t in tag_specs]
        connector = connector_cls(conn_spec.name, conn_spec.config, tag_dicts, self.queue)
        self._connectors[conn_spec.name] = connector
        self._tasks[conn_spec.name] = asyncio.create_task(self._supervise(connector))

    async def _supervise(self, connector: BaseConnector) -> None:
        backoff = 2
        while True:
            try:
                await self._log_status(connector.name, "starting")
                await connector.run()
            except asyncio.CancelledError:
                await self._log_status(connector.name, "stopped")
                raise
            except Exception as exc:
                logger.exception("connector %s crashed: %s", connector.name, exc)
                await self._log_status(connector.name, "error", str(exc))
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

    async def _log_status(self, name: str, status: str, detail: str | None = None) -> None:
        async with session_scope() as session:
            session.add(ConnectionStatusLog(connection_name=name, ts=datetime.now(timezone.utc), status=status, detail=detail))
            await session.commit()

    async def stop_all(self) -> None:
        for task in self._tasks.values():
            task.cancel()
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)

    async def write_tag(self, tag_name: str, value: Any) -> None:
        for conn_name, connector in self._connectors.items():
            tag_specs = self.config.tags_by_connection(conn_name) if self.config else []
            if any(t.name == tag_name for t in tag_specs):
                await connector.write(tag_name, value)
                return
        raise ValueError(f"tag '{tag_name}' not found on any active connection")

    _SENSITIVE_CONFIG_KEYS = ("password", "secret", "token", "key", "credential")

    def health(self) -> list[dict[str, Any]]:
        specs_by_name = {s.name: s for s in self.config.connections} if self.config else {}
        result = []
        for c in self._connectors.values():
            spec = specs_by_name.get(c.name)
            safe_config = {
                k: v
                for k, v in (spec.config if spec else {}).items()
                if not any(s in k.lower() for s in self._SENSITIVE_CONFIG_KEYS)
            }
            result.append(
                {
                    "name": c.name,
                    "protocol": c.protocol,
                    "connected": c.connected,
                    "tag_count": len(c.tags),
                    "config": safe_config,
                }
            )
        return result

    async def _sync_tags_to_db(self, config: HistorianConfig) -> None:
        async with session_scope() as session:
            existing = {t.name: t for t in (await session.execute(select(Tag))).scalars().all()}
            for spec in config.tags:
                tag = existing.get(spec.name)
                if tag is None:
                    tag = Tag(name=spec.name)
                    session.add(tag)
                tag.connection_name = spec.connection
                tag.address = spec.address
                tag.data_type = DataType(spec.data_type)
                tag.engineering_units = spec.engineering_units
                tag.min_value = spec.min_value
                tag.max_value = spec.max_value
                tag.deadband_percent = spec.deadband_percent
                tag.description = spec.description
            await session.flush()

            tag_by_name = {t.name: t for t in (await session.execute(select(Tag))).scalars().all()}
            for spec in config.tags:
                tag = tag_by_name[spec.name]
                existing_alarms = (
                    await session.execute(select(AlarmDefinition).where(AlarmDefinition.tag_id == tag.id))
                ).scalars().all()
                existing_by_condition = {a.condition: a for a in existing_alarms}
                for alarm_spec in spec.alarms:
                    condition = AlarmCondition(alarm_spec["condition"])
                    alarm = existing_by_condition.get(condition)
                    if alarm is None:
                        alarm = AlarmDefinition(tag_id=tag.id, condition=condition)
                        session.add(alarm)
                    alarm.name = alarm_spec.get("name", f"{spec.name} {condition.value}")
                    alarm.setpoint = alarm_spec.get("setpoint")
                    alarm.priority = alarm_spec.get("priority", 5)
                    alarm.message = alarm_spec.get("message")
            await session.commit()
