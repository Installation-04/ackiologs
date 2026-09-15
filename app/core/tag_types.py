"""Shared helper for embedded servers (OPC UA, Modbus, ...) that need to know
every tag's declared data_type up front to build a correctly-typed address/node
space before live values start arriving."""

from __future__ import annotations

from app.db.models import DataType


async def load_tag_data_types() -> dict[str, DataType]:
    from sqlalchemy import select

    from app.db.base import session_scope
    from app.db.models import Tag

    async with session_scope() as session:
        rows = (await session.execute(select(Tag.name, Tag.data_type))).all()
    return {name: data_type for name, data_type in rows}
