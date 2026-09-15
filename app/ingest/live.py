"""In-memory latest-value cache and pub/sub fan-out for the live dashboard and
WebSocket clients. Deliberately not the database: this is the hot path for
"what's the value right now", kept separate from the historized write path."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class LiveValue:
    tag_name: str
    value: Any
    ts: datetime
    quality: str


class LiveBus:
    def __init__(self) -> None:
        self._latest: dict[str, LiveValue] = {}
        self._subscribers: set[asyncio.Queue[LiveValue]] = set()

    def update(self, lv: LiveValue) -> None:
        self._latest[lv.tag_name] = lv
        dead = []
        for q in self._subscribers:
            try:
                q.put_nowait(lv)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self._subscribers.discard(q)

    def snapshot(self) -> dict[str, LiveValue]:
        return dict(self._latest)

    def subscribe(self) -> asyncio.Queue[LiveValue]:
        q: asyncio.Queue[LiveValue] = asyncio.Queue(maxsize=1000)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[LiveValue]) -> None:
        self._subscribers.discard(q)


live_bus = LiveBus()
