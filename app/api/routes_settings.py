from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.core.runtime_settings import runtime_settings
from app.core.security import CurrentUser, get_current_user, require_role
from app.core.settings_registry import SETTINGS
from app.db.models import Role

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("")
async def get_settings_(
    _user: Annotated[CurrentUser, Depends(get_current_user)],
):
    """Every registered setting, grouped by category, with its current live value —
    any authenticated user can view settings (needed to render the dashboard), only
    an admin can change them."""
    current = runtime_settings.all()
    return [
        {
            "key": s.key,
            "category": s.category,
            "label": s.label,
            "type": s.type,
            "value": current.get(s.key, s.default),
            "default": s.default,
            "description": s.description,
            "choices": list(s.choices),
            "min": s.min,
            "max": s.max,
        }
        for s in SETTINGS
    ]


class SettingsUpdateRequest(BaseModel):
    values: dict[str, Any]


@router.put("")
async def update_settings(
    body: SettingsUpdateRequest,
    _user: Annotated[CurrentUser, Depends(require_role(Role.ADMIN))],
):
    """Persist one or more settings and apply any live side-effects (e.g. restarting
    the embedded OPC UA server when its enabled/port/require_auth changed)."""
    try:
        changed = await runtime_settings.set_many(body.values)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    if any(key.startswith("opcua_server.") for key in changed):
        await _apply_opcua_server_state()
    if any(key.startswith("modbus_server.") for key in changed):
        await _apply_modbus_server_state()

    return {"status": "ok", "changed": changed}


async def _apply_opcua_server_state() -> None:
    from app.core.opcua_server import embedded_opcua_server

    should_run = runtime_settings.get("opcua_server.enabled")
    if should_run:
        await embedded_opcua_server.restart()
    else:
        await embedded_opcua_server.stop()


async def _apply_modbus_server_state() -> None:
    from app.core.modbus_server import embedded_modbus_server

    should_run = runtime_settings.get("modbus_server.enabled")
    if should_run:
        await embedded_modbus_server.restart()
    else:
        await embedded_modbus_server.stop()


@router.get("/opcua-server/status")
async def opcua_server_status(
    _user: Annotated[CurrentUser, Depends(get_current_user)],
):
    """Live status of the embedded OPC UA server (the "host your own data
    acquisition server" endpoint), for the dashboard's Endpoints/Connections page —
    distinct from the *configured* opcua_server.enabled setting, which can be on
    while the server has actually failed to bind (e.g. port in use)."""
    from app.core.opcua_server import embedded_opcua_server

    port = runtime_settings.get("opcua_server.port")
    return {
        "running": embedded_opcua_server.running,
        "endpoint": f"opc.tcp://0.0.0.0:{port}/ackiologs/server/",
        "tag_count": embedded_opcua_server.tag_count,
        "require_auth": runtime_settings.get("opcua_server.require_auth"),
    }


@router.get("/modbus-server/status")
async def modbus_server_status(
    _user: Annotated[CurrentUser, Depends(get_current_user)],
):
    """Live status of the embedded Modbus TCP server, plus its register map — a
    Modbus master needs the exact address of each tag to poll it, and there's no
    way to discover that over the protocol itself (no browsing, unlike OPC UA)."""
    from app.core.modbus_server import embedded_modbus_server

    port = runtime_settings.get("modbus_server.port")
    return {
        "running": embedded_modbus_server.running,
        "endpoint": f"0.0.0.0:{port}",
        "tag_count": embedded_modbus_server.tag_count,
        "mapping": embedded_modbus_server.mapping,
    }
