"""In-process signal generator — sine/random/counter/bool toggle. No external
dependencies or field devices required, so `docker compose up` produces live
trending data immediately for demos, tests, and onboarding."""

from __future__ import annotations

import asyncio
import math
import random
import time

from app.connectors.base import BaseConnector


class SimulatorConnector(BaseConnector):
    protocol = "simulator"

    async def run(self) -> None:
        self.connected = True
        interval = float(self.config.get("poll_interval_ms", 1000)) / 1000.0
        start = time.monotonic()
        try:
            while True:
                now = time.monotonic() - start
                for tag in self.tags:
                    value = self._next_value(tag, now)
                    await self.emit(tag["name"], value)
                await asyncio.sleep(interval)
        finally:
            self.connected = False

    def _next_value(self, tag: dict, t: float):
        kind = tag.get("sim", {}).get("kind", "sine")
        params = tag.get("sim", {})
        if kind == "sine":
            amplitude = params.get("amplitude", 50)
            offset = params.get("offset", 50)
            period_s = params.get("period_s", 60)
            noise = params.get("noise", 1.0)
            return offset + amplitude * math.sin(2 * math.pi * t / period_s) + random.uniform(-noise, noise)
        if kind == "random_walk":
            step = params.get("step", 1.0)
            key = f"_rw_{tag['name']}"
            current = getattr(self, key, params.get("offset", 0.0))
            current += random.uniform(-step, step)
            setattr(self, key, current)
            return round(current, 3)
        if kind == "counter":
            key = f"_ctr_{tag['name']}"
            current = getattr(self, key, 0)
            current += params.get("increment", 1)
            setattr(self, key, current)
            return current
        if kind == "bool_toggle":
            period_s = params.get("period_s", 10)
            return int(t // period_s) % 2 == 0
        return random.random()
