"""Embedded Modbus TCP server — the mirror image of app/connectors/modbus_connector.py
(which polls OUT to a PLC/RTU): this lets Ackiologs itself act as a Modbus TCP data
source that PLCs, SCADA, and HMIs which only speak Modbus can read from, instead of
(or alongside) Ackiologs polling Modbus devices directly.

Deliberately read-only: every FLOAT/INT tag is exposed as a pair of input registers
(FC04, IEEE-754 float32 or signed int32, big-endian/high-word-first) and every BOOL
tag as a discrete input bit (FC02) — both are inherently read-only in the Modbus
spec (no function code targets them for writing), so there's no write path to get
wrong. STRING tags have no native Modbus register representation and aren't exposed.

Unlike the embedded OPC UA server's dynamic node space, the register map here is
fixed at server start: real Modbus masters are configured against a static,
pre-agreed address map (that's how the protocol is normally integrated — there's no
browsing), so a tag added after start isn't exposed until the server restarts (same
as a config reload elsewhere in this app). GET /api/settings/modbus-server/status
returns the current map so an integrator knows which address is which tag.
"""

from __future__ import annotations

import asyncio
import logging
import struct
from typing import Any

from app.core.runtime_settings import runtime_settings
from app.core.tag_types import load_tag_data_types
from app.db.models import DataType
from app.ingest.live import LiveValue, live_bus

logger = logging.getLogger("ackiologs.modbus_server")

_REGISTERS_PER_VALUE = 2  # a float32/int32 packed into two 16-bit registers


def _pack_registers(value: Any, data_type: DataType) -> list[int] | None:
    try:
        if data_type == DataType.FLOAT:
            packed = struct.pack(">f", float(value))
        else:  # INT
            packed = struct.pack(">i", int(value))
        return list(struct.unpack(">HH", packed))
    except (TypeError, ValueError, struct.error):
        return None


class EmbeddedModbusServer:
    def __init__(self) -> None:
        self._server_task: asyncio.Task | None = None
        self._forward_task: asyncio.Task | None = None
        self._input_register_block = None
        self._discrete_input_block = None
        self._mapping: dict[str, dict[str, Any]] = {}
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    @property
    def mapping(self) -> dict[str, dict[str, Any]]:
        return dict(self._mapping)

    @property
    def tag_count(self) -> int:
        return len(self._mapping)

    async def start(self) -> None:
        if self._running:
            return
        from pymodbus.datastore import ModbusSequentialDataBlock, ModbusServerContext, ModbusSlaveContext
        from pymodbus.server import StartAsyncTcpServer

        port = runtime_settings.get("modbus_server.port")
        tag_data_types = await load_tag_data_types()

        mapping: dict[str, dict[str, Any]] = {}
        register_values: list[int] = []
        discrete_values: list[bool] = []
        for name, data_type in tag_data_types.items():
            if data_type == DataType.STRING:
                logger.debug("Modbus server: tag %s is STRING, no register representation — skipped", name)
                continue
            if data_type == DataType.BOOL:
                mapping[name] = {"type": "bool", "table": "discrete_input", "address": len(discrete_values)}
                discrete_values.append(False)
            else:
                mapping[name] = {"type": data_type.value, "table": "input_register", "address": len(register_values)}
                register_values.extend([0, 0])

        input_register_block = ModbusSequentialDataBlock(0, register_values or [0])
        discrete_input_block = ModbusSequentialDataBlock(0, discrete_values or [False])
        slave_context = ModbusSlaveContext(
            di=discrete_input_block,
            co=ModbusSequentialDataBlock(0, [False]),
            ir=input_register_block,
            hr=ModbusSequentialDataBlock(0, [0]),
        )
        context = ModbusServerContext(slaves=slave_context, single=True)

        server_task = asyncio.create_task(StartAsyncTcpServer(context=context, address=("0.0.0.0", port)))
        await asyncio.sleep(0)  # let the server task start binding before we report running

        self._server_task = server_task
        self._input_register_block = input_register_block
        self._discrete_input_block = discrete_input_block
        self._mapping = mapping
        self._running = True
        self._forward_task = asyncio.create_task(self._forward_live_values())
        logger.info(
            "Embedded Modbus TCP server started on 0.0.0.0:%s (%d tag(s) mapped)",
            port,
            len(mapping),
        )

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._forward_task is not None:
            self._forward_task.cancel()
            try:
                await self._forward_task
            except (asyncio.CancelledError, Exception):
                pass
            self._forward_task = None
        if self._server_task is not None:
            from pymodbus.server import ServerAsyncStop

            try:
                await ServerAsyncStop()
            except Exception:
                pass
            self._server_task.cancel()
            try:
                await self._server_task
            except (asyncio.CancelledError, Exception):
                pass
            self._server_task = None
        self._input_register_block = None
        self._discrete_input_block = None
        self._mapping = {}
        logger.info("Embedded Modbus TCP server stopped")

    async def restart(self) -> None:
        await self.stop()
        await self.start()

    async def _forward_live_values(self) -> None:
        queue = live_bus.subscribe()
        try:
            for lv in live_bus.snapshot().values():
                self._write_value(lv)
            while True:
                lv = await queue.get()
                self._write_value(lv)
        except asyncio.CancelledError:
            raise
        finally:
            live_bus.unsubscribe(queue)

    def _write_value(self, lv: LiveValue) -> None:
        if lv.value is None:
            return
        entry = self._mapping.get(lv.tag_name)
        if entry is None:
            return
        try:
            if entry["type"] == "bool":
                self._discrete_input_block.setValues(entry["address"] + 1, [bool(lv.value)])
            else:
                data_type = DataType.FLOAT if entry["type"] == "float" else DataType.INT
                registers = _pack_registers(lv.value, data_type)
                if registers is None:
                    return
                self._input_register_block.setValues(entry["address"] + 1, registers)
        except Exception:
            logger.debug("failed to update Modbus register for %s", lv.tag_name, exc_info=True)


embedded_modbus_server = EmbeddedModbusServer()
