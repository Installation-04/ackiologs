import asyncio

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_health_and_tags(tmp_path, monkeypatch):
    monkeypatch.setenv("ACKIOLOGS_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/test.db")
    monkeypatch.setenv("ACKIOLOGS_AUTH_ENABLED", "false")

    from app.main import app

    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            health = await client.get("/health")
            assert health.status_code == 200
            assert health.json() == {"status": "ok"}

            # give the simulator + pipeline a moment to produce at least one sample
            await asyncio.sleep(1.5)

            tags = await client.get("/api/tags")
            assert tags.status_code == 200
            names = {t["name"] for t in tags.json()}
            assert "Sim.Boiler.Temp" in names
