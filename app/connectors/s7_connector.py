"""Siemens S7comm connector for S7-300/400/1200/1500 PLCs via `python-snap7`
(wraps Siemens's own Snap7 library). Tags use snap7's PLC-address-string
syntax directly as `address` — e.g. `"DB1.DBX0.0:BOOL"` (a bit), `"DB1.DBD4:REAL"`
(a float), `"M10.5:BOOL"` (a merker bit), `"DB1:20:STRING[30]"` (a string) — so
there's no separate encoding step to get wrong; whatever snap7 accepts, works.

`snap7`'s Client is a blocking/synchronous API (it wraps a C library), so every
call to it here runs in the default executor to avoid blocking the event loop.
"""

from __future__ import annotations

import asyncio

from app.connectors.base import BaseConnector


class S7Connector(BaseConnector):
    protocol = "s7"

    async def run(self) -> None:
        import snap7

        loop = asyncio.get_running_loop()
        host = self.config["host"]
        rack = self.config.get("rack", 0)
        slot = self.config.get("slot", 1)
        port = self.config.get("port", 102)
        poll_interval = self.config.get("poll_interval_ms", 1000) / 1000.0
        addresses = [t["address"] for t in self.tags]

        client = None
        try:
            while True:
                try:
                    if client is None:
                        client = snap7.client.Client()
                        await loop.run_in_executor(None, client.connect, host, rack, slot, port)
                        self.connected = True
                        self.logger.info("S7 connected to %s (rack %s, slot %s)", host, rack, slot)

                    # read_tags() raises for the whole batch on any failure (snap7
                    # doesn't report per-item errors), so a bad tag address takes
                    # down this connection's polling until fixed — same as any other
                    # connector's connection-level error handling below.
                    values = await loop.run_in_executor(None, client.read_tags, addresses)
                    for tag, value in zip(self.tags, values):
                        await self.emit(tag["name"], value)

                    await asyncio.sleep(poll_interval)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self.connected = False
                    self.logger.warning("S7 connection error (%s); reconnecting in 5s", exc)
                    if client is not None:
                        try:
                            await loop.run_in_executor(None, client.disconnect)
                        except Exception:
                            pass
                        client = None
                    await asyncio.sleep(5)
        finally:
            self.connected = False
            if client is not None:
                try:
                    client.disconnect()
                except Exception:
                    pass

    async def write(self, tag_name: str, value) -> None:
        import snap7

        tag = next((t for t in self.tags if t["name"] == tag_name), None)
        if tag is None:
            raise ValueError(f"unknown tag {tag_name}")

        host = self.config["host"]
        rack = self.config.get("rack", 0)
        slot = self.config.get("slot", 1)
        port = self.config.get("port", 102)
        loop = asyncio.get_running_loop()

        def _write():
            client = snap7.client.Client()
            client.connect(host, rack, slot, port)
            try:
                client.write_tag(tag["address"], value)
            finally:
                client.disconnect()

        await loop.run_in_executor(None, _write)
