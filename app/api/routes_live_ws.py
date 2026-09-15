import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.ingest.live import live_bus

router = APIRouter(tags=["live"])
logger = logging.getLogger("ackiologs.ws")


@router.websocket("/ws/live")
async def live_values(websocket: WebSocket):
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
