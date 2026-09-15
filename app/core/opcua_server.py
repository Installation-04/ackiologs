"""Embedded OPC UA server — the mirror image of app/connectors/opcua_connector.py
(which connects OUT to a PLC's OPC UA server): this lets Ackiologs itself act as
a data acquisition server that other SCADA/historian systems connect IN to,
instead of (or alongside) polling field devices directly. Every currently known
tag is exposed as a live-updating OPC UA variable node under Objects/Tags.

Controlled by the "Embedded OPC UA Server" settings (Settings page / runtime
settings): enabled, port, and whether OPC UA clients must authenticate with a
valid Ackiologs username/password.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.core.runtime_settings import runtime_settings
from app.db.models import DataType
from app.ingest.live import LiveValue, live_bus

logger = logging.getLogger("ackiologs.opcua_server")

NAMESPACE_URI = "http://ackiologs.local/opcua/"

# The node's OPC UA variant type is fixed at creation from this initial value, and
# the embedded server (asyncua) refuses any later write whose variant type doesn't
# match — so every value forwarded to a node must be coerced to this same Python
# type, matching the tag's own declared data_type (Tag.data_type in the DB).
_INITIAL_VALUE: dict[DataType, Any] = {
    DataType.FLOAT: 0.0,
    DataType.INT: 0,
    DataType.BOOL: False,
    DataType.STRING: "",
}


def _coerce_for_type(value: Any, data_type: DataType) -> Any | None:
    try:
        if data_type == DataType.FLOAT:
            return float(value)
        if data_type == DataType.INT:
            return int(value)
        if data_type == DataType.BOOL:
            return bool(value)
        return str(value)
    except (TypeError, ValueError):
        return None


def _infer_data_type(value: Any) -> DataType:
    if isinstance(value, bool):
        return DataType.BOOL
    if isinstance(value, int):
        return DataType.INT
    if isinstance(value, float):
        return DataType.FLOAT
    return DataType.STRING


async def _load_tag_data_types() -> dict[str, DataType]:
    from sqlalchemy import select

    from app.db.base import session_scope
    from app.db.models import Tag

    async with session_scope() as session:
        rows = (await session.execute(select(Tag.name, Tag.data_type))).all()
    return {name: data_type for name, data_type in rows}


class EmbeddedOpcUaServer:
    def __init__(self) -> None:
        self._server = None
        self._tags_folder = None
        self._idx: int | None = None
        self._nodes: dict[str, object] = {}
        self._data_types: dict[str, DataType] = {}
        self._forward_task: asyncio.Task | None = None
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    @property
    def tag_count(self) -> int:
        return len(self._nodes)

    async def start(self) -> None:
        if self._running:
            return
        from asyncua import Server, ua

        port = runtime_settings.get("opcua_server.port")
        server_name = runtime_settings.get("general.site_name") or "Ackiologs"
        require_auth = runtime_settings.get("opcua_server.require_auth")

        tag_data_types = await _load_tag_data_types()

        server = Server()
        await server.init()
        server.set_endpoint(f"opc.tcp://0.0.0.0:{port}/ackiologs/server/")
        server.set_server_name(server_name)
        server.set_security_policy([ua.SecurityPolicyType.NoSecurity])

        if require_auth:
            server.iserver.user_manager = await _build_user_manager()

        idx = await server.register_namespace(NAMESPACE_URI)
        objects = server.get_objects_node()
        tags_folder = await objects.add_folder(idx, "Tags")

        nodes: dict[str, object] = {}
        for name, data_type in tag_data_types.items():
            node = await tags_folder.add_variable(idx, name, _INITIAL_VALUE[data_type])
            nodes[name] = node

        await server.start()

        self._server = server
        self._tags_folder = tags_folder
        self._idx = idx
        self._nodes = nodes
        self._data_types = dict(tag_data_types)
        self._running = True
        self._forward_task = asyncio.create_task(self._forward_live_values())
        logger.info(
            "Embedded OPC UA server started at opc.tcp://0.0.0.0:%s/ackiologs/server/ "
            "(%d tag(s), auth=%s)",
            port,
            len(nodes),
            require_auth,
        )

    async def ensure_tag(self, name: str, data_type: DataType | None = None) -> None:
        """Add a node for a tag that didn't exist when the server started (e.g. a
        new tag picked up by a config reload, or the first live value seen for a
        tag not yet in the DB). No-op if already present or the server isn't
        running. `data_type` defaults to FLOAT when not known by the caller."""
        if not self._running or name in self._nodes or self._tags_folder is None:
            return
        resolved_type = data_type or DataType.FLOAT
        node = await self._tags_folder.add_variable(self._idx, name, _INITIAL_VALUE[resolved_type])
        self._nodes[name] = node
        self._data_types[name] = resolved_type

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._forward_task is not None:
            self._forward_task.cancel()
            try:
                await self._forward_task
            except (asyncio.CancelledError, Exception):
                pass
            self._forward_task = None
        if self._server is not None:
            await self._server.stop()
            self._server = None
        self._nodes = {}
        self._data_types = {}
        self._tags_folder = None
        logger.info("Embedded OPC UA server stopped")

    async def restart(self) -> None:
        await self.stop()
        await self.start()

    async def _forward_live_values(self) -> None:
        queue = live_bus.subscribe()
        try:
            for lv in live_bus.snapshot().values():
                await self._write_value(lv)
            while True:
                lv = await queue.get()
                await self._write_value(lv)
        except asyncio.CancelledError:
            raise
        finally:
            live_bus.unsubscribe(queue)

    async def _write_value(self, lv: LiveValue) -> None:
        if lv.value is None:
            return
        node = self._nodes.get(lv.tag_name)
        if node is None:
            await self.ensure_tag(lv.tag_name, _infer_data_type(lv.value))
            node = self._nodes.get(lv.tag_name)
            if node is None:
                return
        data_type = self._data_types.get(lv.tag_name, DataType.FLOAT)
        coerced = _coerce_for_type(lv.value, data_type)
        if coerced is None:
            return
        try:
            await node.write_value(coerced)
        except Exception:
            logger.debug("failed to update OPC UA node for %s", lv.tag_name, exc_info=True)


async def _build_user_manager():
    """A UserManager whose get_user() is called synchronously by asyncua's session
    handling — so users are snapshotted into memory once, here, at server start
    (async, where we can query the DB) rather than looked up per-login (which
    would need a sync-from-async DB call). Restart the embedded server (toggle it
    off/on in Settings) to pick up new/changed users."""
    from asyncua.crypto.permission_rules import User as OpcUaUser
    from asyncua.crypto.permission_rules import UserRole
    from asyncua.server.user_managers import UserManager
    from sqlalchemy import select

    from app.core.security import verify_password
    from app.db.base import session_scope
    from app.db.models import Role, User

    async with session_scope() as session:
        rows = (await session.execute(select(User).where(User.disabled == False))).scalars().all()  # noqa: E712
    snapshot = {u.username: (u.hashed_password, u.role) for u in rows}

    class _AckiologsUserManager(UserManager):
        def get_user(self, iserver, username=None, password=None, certificate=None):
            if not username or not password:
                return None
            entry = snapshot.get(username)
            if entry is None:
                return None
            hashed_password, role = entry
            if not verify_password(password, hashed_password):
                return None
            return OpcUaUser(role=UserRole.Admin if role == Role.ADMIN else UserRole.User, name=username)

    return _AckiologsUserManager()


embedded_opcua_server = EmbeddedOpcUaServer()
