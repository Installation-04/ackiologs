import logging

from sqlalchemy import text

from app.db.base import Base, engine, is_postgres

logger = logging.getLogger(__name__)


async def init_db() -> None:
    """Create all tables, and — on Postgres — enable TimescaleDB and convert tag_values
    into a hypertable (for storage/query efficiency; retention is handled uniformly for
    every backend by app.ingest.retention's background pruner, driven by the live
    "Data Retention & Compression" setting on the Settings page, not by a Timescale-
    native policy fixed at startup — one mechanism, works the same on SQLite, plain
    Postgres, and TimescaleDB, and is editable without a restart).
    Safe to call on every startup (all operations are idempotent). Each TimescaleDB
    step runs in its own transaction: a plain Postgres instance (no TimescaleDB
    extension installed) is a supported deployment, and one step failing must not
    abort the Postgres transaction subsequent steps run in."""

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    if not is_postgres():
        return

    if not await _try_enable_timescale():
        logger.warning("TimescaleDB extension not available; using a plain Postgres table for tag_values.")
        return

    await _try_create_hypertable()


async def _try_enable_timescale() -> bool:
    try:
        async with engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS timescaledb"))
        return True
    except Exception:
        return False


async def _try_create_hypertable() -> bool:
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "SELECT create_hypertable('tag_values', 'ts', "
                    "if_not_exists => TRUE, migrate_data => TRUE)"
                )
            )
        return True
    except Exception:
        logger.warning("TimescaleDB hypertable creation failed; continuing with a plain Postgres table.")
        return False
