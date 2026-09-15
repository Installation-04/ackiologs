"""EtherNet/IP (CIP) connector for Allen-Bradley / Rockwell Automation PLCs —
CompactLogix, ControlLogix, Micro800 — via `pycomm3`. Tags are addressed by
their symbolic PLC name (including UDT members / array indices, e.g.
`Program:MainProgram.Line1.Speed` or `Recipe[3].Setpoint`), not a numeric
register, since that's how Logix-family controllers actually expose data.

`pycomm3`'s driver is a blocking/synchronous API, so every call to it here
runs in the default executor to avoid blocking the event loop.
"""

from __future__ import annotations

import asyncio

from app.connectors.base import BaseConnector


class EtherNetIpConnector(BaseConnector):
    protocol = "ethernetip"

    async def run(self) -> None:
        from pycomm3 import LogixDriver

        loop = asyncio.get_running_loop()
        path = self._path()
        poll_interval = self.config.get("poll_interval_ms", 1000) / 1000.0
        tag_names = [t["address"] for t in self.tags]

        driver = None
        try:
            while True:
                try:
                    if driver is None:
                        driver = LogixDriver(path)
                        await loop.run_in_executor(None, driver.open)
                        self.connected = True
                        self.logger.info("EtherNet/IP connected to %s (%d tags)", path, len(tag_names))

                    results = await loop.run_in_executor(None, driver.read, *tag_names)
                    if len(tag_names) == 1:
                        results = [results]
                    for tag, result in zip(self.tags, results):
                        if result is None or getattr(result, "error", None):
                            await self.emit(tag["name"], None, quality="bad")
                        else:
                            await self.emit(tag["name"], result.value)

                    await asyncio.sleep(poll_interval)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self.connected = False
                    self.logger.warning("EtherNet/IP connection error (%s); reconnecting in 5s", exc)
                    if driver is not None:
                        try:
                            await loop.run_in_executor(None, driver.close)
                        except Exception:
                            pass
                        driver = None
                    await asyncio.sleep(5)
        finally:
            self.connected = False
            if driver is not None:
                try:
                    driver.close()
                except Exception:
                    pass

    def _path(self) -> str:
        host = self.config["host"]
        slot = self.config.get("slot")
        return f"{host}/{slot}" if slot is not None else host

    async def write(self, tag_name: str, value) -> None:
        from pycomm3 import LogixDriver

        tag = next((t for t in self.tags if t["name"] == tag_name), None)
        if tag is None:
            raise ValueError(f"unknown tag {tag_name}")

        loop = asyncio.get_running_loop()

        def _write():
            with LogixDriver(self._path()) as driver:
                return driver.write((tag["address"], value))

        result = await loop.run_in_executor(None, _write)
        if result is None or getattr(result, "error", None):
            raise RuntimeError(f"EtherNet/IP write failed: {getattr(result, 'error', 'unknown error')}")
