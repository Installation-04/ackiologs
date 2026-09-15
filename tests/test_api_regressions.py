"""Regression tests for bugs found testing the merged app: unhandled 500s on tag
writes, bucketed history breaking on Postgres (decimal.Decimal from EXTRACT), and
config reload not actually refreshing the running ingest pipeline. Runs against
SQLite by default; CI also runs it against a real Postgres service container
(ACKIOLOGS_DATABASE_URL preset) to catch dialect-specific issues raw SQLite
testing can't."""

import asyncio
import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    if "ACKIOLOGS_DATABASE_URL" not in os.environ:
        monkeypatch.setenv("ACKIOLOGS_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/test.db")
    monkeypatch.setenv("ACKIOLOGS_AUTH_ENABLED", "true")

    from app.main import app

    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            await asyncio.sleep(1.5)  # let the simulator produce a few samples
            yield c


async def _make_admin_and_login(client: AsyncClient, username: str) -> dict:
    from app.core.security import hash_password
    from app.db.base import session_scope
    from app.db.models import Role, User

    async with session_scope() as session:
        session.add(User(username=username, hashed_password=hash_password("testpass123"), role=Role.ADMIN))
        await session.commit()

    login = await client.post("/api/auth/token", data={"username": username, "password": "testpass123"})
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.mark.asyncio
async def test_bucketed_history_does_not_crash(client: AsyncClient):
    headers = await _make_admin_and_login(client, "history-tester")

    # Raw mode (always worked).
    raw = await client.get("/api/history/Sim.Boiler.Temp?interval_seconds=0", headers=headers)
    assert raw.status_code == 200
    assert raw.json()["mode"] == "raw"

    # Bucketed mode: on Postgres, EXTRACT(epoch ...) returns decimal.Decimal, which
    # datetime.fromtimestamp() used to reject outright (a 500, not a 4xx).
    bucketed = await client.get("/api/history/Sim.Boiler.Temp?interval_seconds=1", headers=headers)
    assert bucketed.status_code == 200
    body = bucketed.json()
    assert body["mode"] == "bucketed"
    for point in body["points"]:
        assert isinstance(point["avg"], (float, type(None)))


@pytest.mark.asyncio
async def test_write_to_unsupported_connector_is_400_not_500(client: AsyncClient):
    headers = await _make_admin_and_login(client, "write-tester")

    # The Simulator connector doesn't implement write() — used to be an unhandled
    # NotImplementedError surfacing as a raw 500.
    res = await client.post("/api/tags/Sim.Boiler.Temp/write", headers=headers, json={"value": 99})
    assert res.status_code == 400

    # An unknown tag — used to be an unhandled ValueError surfacing as a raw 500.
    res = await client.post("/api/tags/Not.A.Real.Tag/write", headers=headers, json={"value": 1})
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_config_reload_updates_running_pipeline_immediately(client: AsyncClient):
    """POST /api/config/reload claims tag/alarm edits take effect immediately — verify
    the running ingest pipeline's in-memory metadata is actually refreshed, not just
    the database (it used to only update the DB; the pipeline kept stale metadata
    until a restart)."""
    headers = await _make_admin_and_login(client, "reload-tester")

    res = await client.post("/api/config/reload", headers=headers)
    assert res.status_code == 200

    from app.main import app

    pipeline = app.state.pipeline
    assert "Sim.Boiler.Temp" in pipeline._tag_meta
    assert "Sim.Boiler.Temp" in pipeline._alarms_by_tag
