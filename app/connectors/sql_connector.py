"""Generic SQL/database polling connector — for historians, MES, ERP, or any
system that only exposes its data through a database rather than a protocol
or API. Each tag is its own arbitrary read-only SQL query against an external
database (distinct from Ackiologs' own storage database); the first column of
the first returned row is the value.

Queries come from `config/tags.yaml`, which is operator-authored, not
remote/untrusted input — same trust level as any other setting in that file.

Requires an async SQLAlchemy driver for the target database to be installed.
`asyncpg` (Postgres) and `aiosqlite` (SQLite) are already dependencies, so
`postgresql+asyncpg://...` and `sqlite+aiosqlite://...` work out of the box;
other databases work too if their async driver package is installed
(e.g. `aiomysql` for `mysql+aiomysql://...`).
"""

from __future__ import annotations

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.connectors.base import BaseConnector


class SqlConnector(BaseConnector):
    protocol = "sql"

    async def run(self) -> None:
        database_url = self.config["database_url"]
        poll_interval = self.config.get("poll_interval_ms", 5000) / 1000.0

        engine = create_async_engine(database_url, pool_pre_ping=True)
        try:
            while True:
                try:
                    any_ok = False
                    async with engine.connect() as conn:
                        for tag in self.tags:
                            try:
                                result = await conn.execute(text(tag["address"]))
                                row = result.first()
                                value = row[0] if row is not None else None
                                await self.emit(tag["name"], value, quality="good" if value is not None else "bad")
                                any_ok = any_ok or value is not None
                            except asyncio.CancelledError:
                                raise
                            except Exception as exc:
                                await self.emit(tag["name"], None, quality="bad")
                                self.logger.debug("SQL query failed for %s: %s", tag["name"], exc)
                    self.connected = any_ok
                    await asyncio.sleep(poll_interval)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self.connected = False
                    self.logger.warning("SQL connection error (%s); retrying in 5s", exc)
                    await asyncio.sleep(5)
        finally:
            self.connected = False
            await engine.dispose()

    async def write(self, tag_name: str, value) -> None:
        raise NotImplementedError(
            "sql connector is read-only by design — writing arbitrary values into an "
            "external database's schema has no safe general contract"
        )
