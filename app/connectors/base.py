"""The connector interface every protocol driver implements.

Ackiologs is protocol-agnostic by design: the ingestion pipeline, storage, API and
dashboard only ever see `Sample` objects on a queue. Adding support for a new
industrial protocol means writing one class here and registering it — nothing else
in the system needs to change. Shipped today: OPC UA, Modbus (TCP/RTU), MQTT (Sparkplug-
friendly), and a Simulator for demos/tests. BACnet/IP, DNP3 and EtherNet/IP-CIP follow
the same shape (see README "Adding a protocol").
"""

from __future__ import annotations

import abc
import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(slots=True)
class Sample:
    tag_name: str
    value: Any
    ts: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    quality: str = "good"


class ConnectorError(RuntimeError):
    pass


class BaseConnector(abc.ABC):
    """One instance per configured connection (e.g. one OPC UA server, one MQTT broker,
    one Modbus slave). Connectors run as background asyncio tasks supervised by the
    ConnectorSupervisor and push Samples onto a shared asyncio.Queue.
    """

    protocol: str = "base"

    def __init__(self, name: str, config: dict[str, Any], tags: list[dict[str, Any]], queue: asyncio.Queue[Sample]):
        self.name = name
        self.config = config
        self.tags = tags
        self.queue = queue
        self.logger = logging.getLogger(f"ackiologs.connector.{name}")
        self.connected = False

    async def emit(self, tag_name: str, value: Any, quality: str = "good", ts: datetime | None = None) -> None:
        sample = Sample(tag_name=tag_name, value=value, quality=quality, ts=ts or datetime.now(timezone.utc))
        try:
            self.queue.put_nowait(sample)
        except asyncio.QueueFull:
            self.logger.warning("ingest queue full — dropping sample for %s", tag_name)

    @abc.abstractmethod
    async def run(self) -> None:
        """Connect, subscribe/poll, and emit() samples forever until cancelled."""

    async def write(self, tag_name: str, value: Any) -> None:
        """Optional: write a value back out to the field device (setpoint changes etc.)."""
        raise NotImplementedError(f"{self.protocol} connector does not support writes")

    async def health(self) -> dict[str, Any]:
        return {"name": self.name, "protocol": self.protocol, "connected": self.connected}
