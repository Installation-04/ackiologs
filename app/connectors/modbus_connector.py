"""Modbus TCP / RTU polling connector — covers the huge installed base of PLCs,
VFDs, meters and RTUs that only speak Modbus. Polls holding/input registers and
coils on a fixed interval per tag (Modbus has no native subscribe/publish)."""

from __future__ import annotations

import asyncio
import struct

from app.connectors.base import BaseConnector

_REGISTER_TABLES = {"holding", "input", "coil", "discrete_input"}


class ModbusConnector(BaseConnector):
    protocol = "modbus"

    async def run(self) -> None:
        mode = self.config.get("mode", "tcp")  # tcp | rtu
        poll_interval = self.config.get("poll_interval_ms", 1000) / 1000.0

        client = await self._make_client(mode)

        while True:
            try:
                if not client.connected:
                    await client.connect()
                self.connected = client.connected
                for tag in self.tags:
                    await self._poll_tag(client, tag)
                await asyncio.sleep(poll_interval)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.connected = False
                self.logger.warning("Modbus poll error (%s); retrying in 5s", exc)
                await asyncio.sleep(5)

    async def _make_client(self, mode: str):
        if mode == "rtu":
            from pymodbus.client import AsyncModbusSerialClient

            return AsyncModbusSerialClient(
                port=self.config["serial_port"],
                baudrate=self.config.get("baudrate", 9600),
                parity=self.config.get("parity", "N"),
                stopbits=self.config.get("stopbits", 1),
                bytesize=self.config.get("bytesize", 8),
            )
        from pymodbus.client import AsyncModbusTcpClient

        return AsyncModbusTcpClient(host=self.config["host"], port=self.config.get("port", 502))

    async def _poll_tag(self, client, tag: dict) -> None:
        addr = tag["address"]  # "holding:40001" / "coil:5" / "input:30002:float32"
        parts = addr.split(":")
        table, register = parts[0], int(parts[1])
        encoding = parts[2] if len(parts) > 2 else tag.get("data_type", "int16")
        unit = self.config.get("unit_id", 1)

        try:
            if table == "holding":
                count = 2 if encoding in ("float32", "int32", "uint32") else 1
                rr = await client.read_holding_registers(register, count=count, slave=unit)
            elif table == "input":
                count = 2 if encoding in ("float32", "int32", "uint32") else 1
                rr = await client.read_input_registers(register, count=count, slave=unit)
            elif table == "coil":
                rr = await client.read_coils(register, count=1, slave=unit)
            elif table == "discrete_input":
                rr = await client.read_discrete_inputs(register, count=1, slave=unit)
            else:
                raise ValueError(f"unknown modbus table '{table}'")
        except Exception as exc:
            await self.emit(tag["name"], None, quality="bad")
            self.logger.debug("read failed for %s: %s", tag["name"], exc)
            return

        if rr.isError():
            await self.emit(tag["name"], None, quality="bad")
            return

        value = self._decode(rr, table, encoding)
        await self.emit(tag["name"], value)

    @staticmethod
    def _decode(rr, table: str, encoding: str):
        if table in ("coil", "discrete_input"):
            return bool(rr.bits[0])

        regs = rr.registers
        if encoding == "int16":
            return struct.unpack(">h", struct.pack(">H", regs[0]))[0]
        if encoding == "uint16":
            return regs[0]
        raw = struct.pack(">HH", regs[0], regs[1])
        if encoding == "float32":
            return struct.unpack(">f", raw)[0]
        if encoding == "int32":
            return struct.unpack(">i", raw)[0]
        if encoding == "uint32":
            return struct.unpack(">I", raw)[0]
        return regs[0]

    async def write(self, tag_name: str, value) -> None:
        tag = next((t for t in self.tags if t["name"] == tag_name), None)
        if tag is None:
            raise ValueError(f"unknown tag {tag_name}")
        table, register = tag["address"].split(":")[:2]
        register = int(register)
        unit = self.config.get("unit_id", 1)
        client = await self._make_client(self.config.get("mode", "tcp"))
        await client.connect()
        try:
            if table == "coil":
                await client.write_coil(register, bool(value), slave=unit)
            elif table == "holding":
                await client.write_register(register, int(value), slave=unit)
            else:
                raise ValueError(f"table '{table}' is read-only")
        finally:
            client.close()
