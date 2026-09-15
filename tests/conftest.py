import pytest
import pytest_asyncio


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    """app.config.get_settings() is @lru_cache'd process-wide, so without this,
    whichever test runs first "locks in" its monkeypatched env vars for every test
    that follows in the same pytest process — a real test-isolation bug, not just a
    theoretical one (it broke test_api_smoke.py as soon as a second test file that
    used different settings was added)."""
    from app.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest_asyncio.fixture(autouse=True)
async def _dispose_db_engine():
    """app.db.base.engine is a module-level singleton whose pooled asyncpg
    connections are bound to the event loop they were opened on. Production only
    ever has one event loop for the process's lifetime, but pytest-asyncio gives
    each test its own — without disposing here, the next test's loop hits a pool
    full of connections tied to a now-closed loop ("Event loop is closed" on
    cleanup). Harmless no-op against SQLite; only matters for Postgres."""
    yield
    from app.db.base import engine

    await engine.dispose()
