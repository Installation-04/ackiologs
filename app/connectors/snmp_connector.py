"""SNMP connector — polls OIDs from network gear, UPSes, PDUs, environmental
sensors and other devices that only expose data via SNMP. SNMPv1/v2c
(community string) today; `pysnmp`'s v3arch API also supports SNMPv3
(authPriv) if that's needed later.

Tag `address` is the OID (dotted or symbolic isn't resolved — use the numeric
form, e.g. `"1.3.6.1.2.1.1.3.0"` for sysUpTime). `pysnmp`'s hlapi is natively
asyncio (v3arch.asyncio) — no executor thread needed.
"""

from __future__ import annotations

import asyncio

from app.connectors.base import BaseConnector


class SnmpConnector(BaseConnector):
    protocol = "snmp"

    async def run(self) -> None:
        from pysnmp.hlapi.v3arch.asyncio import CommunityData, ContextData, SnmpEngine, UdpTransportTarget

        host = self.config["host"]
        port = self.config.get("port", 161)
        community = self.config.get("community", "public")
        snmp_version = self.config.get("version", "2c")  # "1" or "2c"
        timeout = self.config.get("timeout_seconds", 3)
        poll_interval = self.config.get("poll_interval_ms", 5000) / 1000.0

        engine = SnmpEngine()
        auth = CommunityData(community, mpModel=0 if snmp_version == "1" else 1)

        try:
            while True:
                try:
                    target = await UdpTransportTarget.create((host, port), timeout=timeout, retries=1)
                    any_ok = False
                    for tag in self.tags:
                        value = await self._read_oid(engine, auth, target, tag["address"])
                        if value is None:
                            await self.emit(tag["name"], None, quality="bad")
                        else:
                            await self.emit(tag["name"], value)
                            any_ok = True
                    self.connected = any_ok or not self.tags
                    await asyncio.sleep(poll_interval)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self.connected = False
                    self.logger.warning("SNMP error (%s); retrying in 5s", exc)
                    await asyncio.sleep(5)
        finally:
            self.connected = False
            engine.close_dispatcher()

    @staticmethod
    async def _read_oid(engine, auth, target, oid: str):
        from pysnmp.hlapi.v3arch.asyncio import ContextData, ObjectIdentity, ObjectType, get_cmd

        error_indication, error_status, _error_index, var_binds = await get_cmd(
            engine, auth, target, ContextData(), ObjectType(ObjectIdentity(oid))
        )
        if error_indication or error_status:
            return None
        if not var_binds:
            return None
        _name, value = var_binds[0]
        # pysnmp values are its own typed objects (Integer32, OctetString, ...);
        # str() gives a readable value, prettyPrint() the same — coerce numerics
        # so they store/chart as numbers rather than strings.
        text = str(value)
        try:
            return float(text) if "." in text else int(text)
        except ValueError:
            return text

    async def write(self, tag_name: str, value) -> None:
        raise NotImplementedError("snmp connector does not support writes (SNMP SET is not implemented)")
