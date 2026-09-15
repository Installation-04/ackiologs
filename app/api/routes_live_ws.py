import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from app.core.security import verify_token
from app.ingest.live import live_bus

router = APIRouter(tags=["live"])
logger = logging.getLogger("ackiologs.ws")


@router.websocket("/ws/live")
async def live_values(websocket: WebSocket, token: str | None = None):
    # Browsers can't attach an Authorization header to a WebSocket handshake, so the
    # dashboard passes the JWT as a query param instead; verified the same way as the
    # REST API so this stream can't be used to read live tag data without a token.
    if verify_token(token) is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()
    for lv in live_bus.snapshot().values():
        await websocket.send_json({"tag": lv.tag_name, "value": lv.value, "ts": lv.ts.isoformat(), "quality": lv.quality})

    queue = live_bus.subscribe()
    try:
        while True:
            lv = await queue.get()
            await websocket.send_json({"tag": lv.tag_name, "value": lv.value, "ts": lv.ts.isoformat(), "quality": lv.quality})
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    finally:
        live_bus.unsubscribe(queue)
