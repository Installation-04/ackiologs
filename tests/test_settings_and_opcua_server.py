"""Tests for the runtime Settings system, alarm acknowledgment, retention pruning,
and the embedded OPC UA server ("host your own data acquisition server")."""

import asyncio
import os
from datetime import datetime, timedelta, timezone

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
            await asyncio.sleep(1.0)  # let the simulator produce a few samples
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
async def test_settings_get_and_put(client: AsyncClient):
    headers = await _make_admin_and_login(client, "settings-tester")

    res = await client.get("/api/settings", headers=headers)
    assert res.status_code == 200
    body = res.json()
    keys = {s["key"] for s in body}
    assert "retention.days" in keys
    assert "opcua_server.port" in keys

    res = await client.put("/api/settings", headers=headers, json={"values": {"retention.days": 30}})
    assert res.status_code == 200
    assert "retention.days" in res.json()["changed"]

    res = await client.get("/api/settings", headers=headers)
    updated = {s["key"]: s["value"] for s in res.json()}
    assert updated["retention.days"] == 30

    # invalid value is rejected with a 400, not applied
    res = await client.put("/api/settings", headers=headers, json={"values": {"security.access_token_expire_minutes": 1}})
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_settings_non_admin_cannot_write(client: AsyncClient):
    from app.core.security import hash_password
    from app.db.base import session_scope
    from app.db.models import Role, User

    async with session_scope() as session:
        session.add(User(username="viewer", hashed_password=hash_password("testpass123"), role=Role.VIEWER))
        await session.commit()
    login = await client.post("/api/auth/token", data={"username": "viewer", "password": "testpass123"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    res = await client.get("/api/settings", headers=headers)
    assert res.status_code == 200  # viewing is allowed for any authenticated user

    res = await client.put("/api/settings", headers=headers, json={"values": {"retention.days": 5}})
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_alarm_acknowledgment(client: AsyncClient):
    headers = await _make_admin_and_login(client, "ack-tester")

    from app.db.base import session_scope
    from app.db.models import AlarmEvent, AlarmState

    async with session_scope() as session:
        session.add(AlarmEvent(alarm_id=1, tag_id=1, state=AlarmState.ACTIVE, value=99.0, message="High temp"))
        await session.commit()

    res = await client.get("/api/alarms/events", headers=headers)
    assert res.status_code == 200
    events = res.json()
    assert any(e["alarm_id"] == 1 and e["state"] == "active" for e in events)

    res = await client.post("/api/alarms/events/1/ack", headers=headers)
    assert res.status_code == 200
    assert res.json()["acked_by"] == "ack-tester"

    res = await client.get("/api/alarms/events", headers=headers)
    events = res.json()
    acked = [e for e in events if e["alarm_id"] == 1 and e["state"] == "acked"]
    assert len(acked) == 1
    assert acked[0]["acked_by"] == "ack-tester"
    # the original ACTIVE event is still present — ack appends, never rewrites
    assert any(e["alarm_id"] == 1 and e["state"] == "active" for e in events)

    # acking an alarm with no events at all is a 404, not a 500
    res = await client.post("/api/alarms/events/999/ack", headers=headers)
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_retention_pruner_deletes_old_samples_only(client: AsyncClient):
    from app.db.base import session_scope
    from app.db.models import Tag, TagValue
    from app.ingest.retention import _prune_once
    from app.core.runtime_settings import runtime_settings

    now = datetime.now(timezone.utc)
    async with session_scope() as session:
        tag = Tag(name="RetentionTestTag", connection_name="sim", address="1")
        session.add(tag)
        await session.flush()
        session.add(TagValue(tag_id=tag.id, ts=now - timedelta(days=10), value_float=1.0))
        session.add(TagValue(tag_id=tag.id, ts=now - timedelta(hours=1), value_float=2.0))
        await session.commit()
        tag_id = tag.id

    await runtime_settings.set_many({"retention.days": 5})
    await _prune_once()

    async with session_scope() as session:
        from sqlalchemy import select

        remaining = (await session.execute(select(TagValue).where(TagValue.tag_id == tag_id))).scalars().all()
    assert len(remaining) == 1
    assert remaining[0].value_float == 2.0

    # retention.days = 0 means "keep forever" — pruning is a no-op
    await runtime_settings.set_many({"retention.days": 0})
    await _prune_once()
    async with session_scope() as session:
        from sqlalchemy import select

        remaining = (await session.execute(select(TagValue).where(TagValue.tag_id == tag_id))).scalars().all()
    assert len(remaining) == 1


@pytest.mark.asyncio
async def test_embedded_opcua_server_exposes_live_tag_values(client: AsyncClient):
    """End-to-end: enable the embedded OPC UA server via the Settings API, then
    connect a real asyncua Client and read back a tag the simulator is producing."""
    headers = await _make_admin_and_login(client, "opcua-tester")

    res = await client.put(
        "/api/settings",
        headers=headers,
        json={"values": {"opcua_server.enabled": True, "opcua_server.port": 48601, "opcua_server.require_auth": False}},
    )
    assert res.status_code == 200

    from app.core.opcua_server import embedded_opcua_server

    assert embedded_opcua_server.running
    await asyncio.sleep(0.5)  # let a live sample or two flow through

    from asyncua import Client

    opcua_client = Client(url="opc.tcp://127.0.0.1:48601/ackiologs/server/")
    await opcua_client.connect()
    try:
        objects = opcua_client.get_objects_node()
        children = await objects.get_children()
        tags_folder = None
        for c in children:
            if (await c.read_browse_name()).Name == "Tags":
                tags_folder = c
                break
        assert tags_folder is not None

        tag_children = await tags_folder.get_children()
        names = {(await c.read_browse_name()).Name for c in tag_children}
        assert "Sim.Boiler.Temp" in names
    finally:
        await opcua_client.disconnect()

    # disabling via Settings actually stops the server
    res = await client.put("/api/settings", headers=headers, json={"values": {"opcua_server.enabled": False}})
    assert res.status_code == 200
    assert not embedded_opcua_server.running
