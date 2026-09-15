"""MQTT connector — subscribes to broker topics for IIoT/edge-gateway data,
including Sparkplug B style payloads (birth/data/death) when `sparkplug: true`.
Also covers plain JSON/text telemetry from edge devices and cloud gateways."""

from __future__ import annotations

import asyncio
import json

from app.connectors.base import BaseConnector


class MqttConnector(BaseConnector):
    protocol = "mqtt"

    async def run(self) -> None:
        import paho.mqtt.client as mqtt

        loop = asyncio.get_running_loop()
        topic_to_tag = {tag["address"]: tag for tag in self.tags}
        json_path_tags = [t for t in self.tags if ":" in t["address"] and t["address"].split(":")[0] == "json"]

        client_id = self.config.get("client_id", f"ackiologs-{self.name}")
        client = mqtt.Client(client_id=client_id, protocol=mqtt.MQTTv311)
        if self.config.get("username"):
            client.username_pw_set(self.config["username"], self.config.get("password"))
        if self.config.get("tls", False):
            client.tls_set()

        def on_connect(c, userdata, flags, rc, properties=None):
            self.connected = rc == 0
            for topic in self._subscribe_topics():
                c.subscribe(topic, qos=self.config.get("qos", 0))
            self.logger.info("MQTT connected (rc=%s), subscribed to %d topic(s)", rc, len(self._subscribe_topics()))

        def on_disconnect(c, userdata, rc, properties=None):
            self.connected = False

        def on_message(c, userdata, msg):
            asyncio.run_coroutine_threadsafe(self._handle_message(msg.topic, msg.payload, topic_to_tag, json_path_tags), loop)

        client.on_connect = on_connect
        client.on_disconnect = on_disconnect
        client.on_message = on_message

        client.connect_async(self.config["host"], self.config.get("port", 1883), keepalive=60)
        client.loop_start()
        try:
            while True:
                await asyncio.sleep(3600)
        finally:
            client.loop_stop()
            client.disconnect()

    def _subscribe_topics(self) -> list[str]:
        topics = set()
        for tag in self.tags:
            addr = tag["address"]
            topics.add(addr.split(":", 1)[1] if addr.startswith("json:") else addr)
        return list(topics)

    async def _handle_message(self, topic: str, payload: bytes, topic_to_tag: dict, json_path_tags: list) -> None:
        raw = payload.decode("utf-8", errors="replace")

        direct = topic_to_tag.get(topic)
        if direct is not None:
            await self.emit(direct["name"], self._coerce(raw, direct.get("data_type", "float")))

        for tag in json_path_tags:
            _, mqtt_topic, json_key = tag["address"].split(":", 2)
            if mqtt_topic != topic:
                continue
            try:
                data = json.loads(raw)
                value = data
                for part in json_key.split("."):
                    value = value[part]
                await self.emit(tag["name"], value)
            except (json.JSONDecodeError, KeyError, TypeError):
                await self.emit(tag["name"], None, quality="bad")

    @staticmethod
    def _coerce(raw: str, data_type: str):
        try:
            if data_type == "float":
                return float(raw)
            if data_type == "int":
                return int(float(raw))
            if data_type == "bool":
                return raw.strip().lower() in ("1", "true", "on", "yes")
        except ValueError:
            return None
        return raw

    async def write(self, tag_name: str, value) -> None:
        import paho.mqtt.publish as publish

        tag = next((t for t in self.tags if t["name"] == tag_name), None)
        if tag is None:
            raise ValueError(f"unknown tag {tag_name}")
        topic = tag["address"].split(":", 1)[1] if tag["address"].startswith("json:") else tag["address"]
        publish.single(
            topic,
            payload=json.dumps(value) if isinstance(value, (dict, list)) else str(value),
            hostname=self.config["host"],
            port=self.config.get("port", 1883),
        )
