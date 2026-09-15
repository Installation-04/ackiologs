"""OPC UA connector — subscribes to node data-change notifications on a UA server.
Covers the dominant protocol for modern PLCs/SCADA (Siemens, Rockwell via gateway,
Beckhoff, Ignition, KEPServerEX, etc.)."""

from __future__ import annotations

import asyncio

from app.connectors.base import BaseConnector


class _SubHandler:
    def __init__(self, connector: "OpcUaConnector", node_to_tag: dict[str, str]):
        self.connector = connector
        self.node_to_tag = node_to_tag

    def datachange_notification(self, node, val, data) -> None:
        tag_name = self.node_to_tag.get(node.nodeid.to_string())
        if tag_name is None:
            return
        status = data.monitored_item.Value.StatusCode
        quality = "good" if status.is_good() else ("uncertain" if status.is_uncertain() else "bad")
        asyncio.create_task(self.connector.emit(tag_name, val, quality=quality))


class OpcUaConnector(BaseConnector):
    protocol = "opcua"

    async def run(self) -> None:
        from asyncua import Client

        endpoint = self.config["endpoint"]
        security_string = self.config.get("security_string")  # e.g. "Basic256Sha256,SignAndEncrypt,cert.der,key.pem"
        username = self.config.get("username")
        password = self.config.get("password")
        publish_interval_ms = self.config.get("publish_interval_ms", 500)

        while True:
            try:
                async with Client(url=endpoint) as client:
                    if security_string:
                        await client.set_security_string(security_string)
                    if username:
                        client.set_user(username)
                        client.set_password(password or "")

                    node_to_tag: dict[str, str] = {}
                    nodes = []
                    for tag in self.tags:
                        node = client.get_node(tag["address"])
                        nodes.append(node)
                        node_to_tag[node.nodeid.to_string()] = tag["name"]

                    handler = _SubHandler(self, node_to_tag)
                    sub = await client.create_subscription(publish_interval_ms, handler)
                    await sub.subscribe_data_change(nodes)

                    self.connected = True
                    self.logger.info("OPC UA connected to %s, subscribed to %d nodes", endpoint, len(nodes))
                    try:
                        while True:
                            await asyncio.sleep(5)
                    finally:
                        self.connected = False
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # connection lost / server unreachable
                self.connected = False
                self.logger.warning("OPC UA connection error (%s); retrying in 5s", exc)
                await asyncio.sleep(5)

    async def write(self, tag_name: str, value) -> None:
        from asyncua import Client, ua

        tag = next((t for t in self.tags if t["name"] == tag_name), None)
        if tag is None:
            raise ValueError(f"unknown tag {tag_name}")
        async with Client(url=self.config["endpoint"]) as client:
            node = client.get_node(tag["address"])
            await node.write_value(ua.DataValue(ua.Variant(value)))
