"""BACnet/IP connector — building automation (AHUs, chillers, VAV boxes,
meters) via `bacpypes3`, BACnet's native transport. One local BACnet device
("Ackiologs") is created per connection and used to poll `present-value` (or
any other property) from remote devices.

Tag `address` format: `"<device_address>:<object-type>:<instance>[:<property>]"`
e.g. `"192.168.1.50:analog-input:3"` (defaults to reading `present-value`) or
`"192.168.1.50:binary-output:1:present-value"`. `device_address` may include a
port (`192.168.1.50:47808`) for a non-default BACnet/IP port.

Unlike the other polling-style connectors here, `bacpypes3` is natively
asyncio — no executor thread needed.
"""

from __future__ import annotations

import asyncio

from app.connectors.base import BaseConnector


class BacnetConnector(BaseConnector):
    protocol = "bacnet"

    async def run(self) -> None:
        from bacpypes3.app import Application
        from bacpypes3.argparse import SimpleArgumentParser

        poll_interval = self.config.get("poll_interval_ms", 5000) / 1000.0
        local_address = self.config.get("local_address", "0.0.0.0")
        device_instance = self.config.get("device_instance", 599999)
        device_name = self.config.get("device_name", f"ackiologs-{self.name}")

        parser = SimpleArgumentParser()
        args = parser.parse_args(
            ["--address", str(local_address), "--name", device_name, "--instance", str(device_instance)]
        )
        app = Application.from_args(args)
        self.connected = True
        try:
            while True:
                any_ok = False
                for tag in self.tags:
                    try:
                        value = await self._read_tag(app, tag["address"])
                        await self.emit(tag["name"], value)
                        any_ok = True
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        await self.emit(tag["name"], None, quality="bad")
                        self.logger.debug("BACnet read failed for %s: %s", tag["name"], exc)
                self.connected = any_ok or not self.tags
                await asyncio.sleep(poll_interval)
        finally:
            self.connected = False
            app.close()

    async def _read_tag(self, app, address: str):
        device_address, object_id, prop = self._parse_address(address)
        return await app.read_property(device_address, object_id, prop)

    @staticmethod
    def _parse_address(address: str) -> tuple[str, str, str]:
        parts = address.split(":")
        if len(parts) == 3:
            device_address, obj_type, instance = parts
            prop = "present-value"
        elif len(parts) == 4:
            device_address, obj_type, instance, prop = parts
        else:
            raise ValueError(
                f"invalid BACnet address '{address}' — expected "
                "'<device_address>:<object-type>:<instance>[:<property>]'"
            )
        return device_address, f"{obj_type}:{instance}", prop

    async def write(self, tag_name: str, value) -> None:
        from bacpypes3.app import Application
        from bacpypes3.argparse import SimpleArgumentParser

        tag = next((t for t in self.tags if t["name"] == tag_name), None)
        if tag is None:
            raise ValueError(f"unknown tag {tag_name}")

        device_address, object_id, prop = self._parse_address(tag["address"])
        parser = SimpleArgumentParser()
        args = parser.parse_args(
            [
                "--address",
                str(self.config.get("local_address", "0.0.0.0")),
                "--name",
                self.config.get("device_name", f"ackiologs-{self.name}"),
                "--instance",
                str(self.config.get("device_instance", 599999)),
            ]
        )
        app = Application.from_args(args)
        try:
            await app.write_property(
                device_address, object_id, prop, value, priority=self.config.get("write_priority")
            )
        finally:
            app.close()
