"""Generic HTTP/REST polling connector — the escape hatch for everything that
doesn't have a dedicated driver: cloud SCADA platforms, vendor equipment APIs,
weather/utility data feeds, a colleague's Flask endpoint. Polls a URL on an
interval and either uses the response body directly (numeric/text) or pulls
one field out of a JSON response.

Tag `address` format:
  - `"<path>"` — GET `<path>` (joined with `base_url` unless it's already an
    absolute URL), use the response body as-is (parsed as a number if
    possible, else kept as text).
  - `"json:<path>:<dotted.key.path>"` — GET `<path>`, parse the response as
    JSON, and extract `<dotted.key.path>` (matching the MQTT connector's own
    `json:<topic>:<key>` convention, for consistency across connectors).
    Since a URL can itself contain colons (`http://host:8080/status`), the
    key path is always everything after the *last* colon in the address.

Multiple tags hitting the same path in one connection share a single request
per poll cycle rather than one request per tag.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict

from app.connectors.base import BaseConnector


class HttpConnector(BaseConnector):
    protocol = "http"

    async def run(self) -> None:
        import httpx

        base_url = self.config.get("base_url", "")
        poll_interval = self.config.get("poll_interval_ms", 5000) / 1000.0
        timeout = self.config.get("timeout_seconds", 10)
        headers = dict(self.config.get("headers", {}))
        if self.config.get("bearer_token"):
            headers["Authorization"] = f"Bearer {self.config['bearer_token']}"

        by_path: dict[str, list[dict]] = defaultdict(list)
        for tag in self.tags:
            path, _ = self._parse_address(tag["address"])
            by_path[path].append(tag)

        async with httpx.AsyncClient(base_url=base_url, headers=headers, timeout=timeout) as client:
            try:
                while True:
                    any_ok = False
                    for path, tags_for_path in by_path.items():
                        try:
                            resp = await client.get(path)
                            resp.raise_for_status()
                            for tag in tags_for_path:
                                await self.emit(tag["name"], self._extract(resp, tag["address"]))
                            any_ok = True
                        except asyncio.CancelledError:
                            raise
                        except Exception as exc:
                            for tag in tags_for_path:
                                await self.emit(tag["name"], None, quality="bad")
                            self.logger.debug("HTTP poll failed for %s: %s", path, exc)
                    self.connected = any_ok
                    await asyncio.sleep(poll_interval)
            finally:
                self.connected = False

    @staticmethod
    def _parse_address(address: str) -> tuple[str, str | None]:
        if address.startswith("json:"):
            path, _, key_path = address[len("json:") :].rpartition(":")
            if not path:
                raise ValueError(f"invalid HTTP address '{address}' — expected 'json:<path>:<dotted.key.path>'")
            return path, key_path
        return address, None

    @classmethod
    def _extract(cls, resp, address: str):
        path, key_path = cls._parse_address(address)
        if key_path is None:
            text = resp.text.strip()
            try:
                return float(text) if "." in text else int(text)
            except ValueError:
                return text

        data = resp.json()
        value = data
        for part in key_path.split("."):
            if isinstance(value, list):
                value = value[int(part)]
            else:
                value = value[part]
        return value

    async def write(self, tag_name: str, value) -> None:
        raise NotImplementedError(
            "http connector is read-only — write APIs vary too much to guess a contract; "
            "add a dedicated connector if the target API needs writes"
        )
