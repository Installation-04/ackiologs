"""The schema for runtime-editable settings (the dashboard's Settings page).

Every setting here is genuinely wired to live behavior somewhere in the app —
nothing in this registry is decorative. Settings that require a process
restart to change (database backend, secret key, CORS origins, ...) live in
`app/config.py`/`.env` instead and are deliberately not duplicated here; see
the wiki's Configuration Reference for those.

Categories loosely follow what a commercial historian's settings/admin page
exposes: general site identity, data retention & compression, alarm
management (ISA-18.2 acknowledgment), security, an embedded OPC UA server
(this instance acting as its own DAQ server for other clients), and display
preferences.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SettingDef:
    key: str
    category: str
    label: str
    type: str  # "bool" | "int" | "float" | "string" | "enum"
    default: Any
    description: str = ""
    choices: tuple[str, ...] = ()
    min: float | None = None
    max: float | None = None

    def coerce(self, raw: str) -> Any:
        if self.type == "bool":
            return raw.strip().lower() in ("1", "true", "yes", "on")
        if self.type == "int":
            return int(raw)
        if self.type == "float":
            return float(raw)
        if self.type == "enum":
            if raw not in self.choices:
                raise ValueError(f"'{raw}' is not one of {self.choices}")
            return raw
        return raw

    def validate(self, value: Any) -> None:
        if self.type in ("int", "float"):
            if self.min is not None and value < self.min:
                raise ValueError(f"{self.key} must be >= {self.min}")
            if self.max is not None and value > self.max:
                raise ValueError(f"{self.key} must be <= {self.max}")
        if self.type == "enum" and value not in self.choices:
            raise ValueError(f"{self.key} must be one of {self.choices}")

    def to_str(self, value: Any) -> str:
        if self.type == "bool":
            return "true" if value else "false"
        return str(value)


SETTINGS: list[SettingDef] = [
    SettingDef(
        key="general.site_name",
        category="General",
        label="Site name",
        type="string",
        default="Ackiologs",
        description="Shown in the dashboard header and the embedded OPC UA server's name.",
    ),
    SettingDef(
        key="general.timezone",
        category="General",
        label="Display timezone",
        type="string",
        default="UTC",
        description="IANA timezone name (e.g. America/Chicago) used to render timestamps in the dashboard. Storage is always UTC.",
    ),
    SettingDef(
        key="retention.days",
        category="Data Retention & Compression",
        label="History retention (days)",
        type="int",
        default=0,
        min=0,
        description="0 = keep forever. Prunes tag_values older than this on a background schedule (works on SQLite and plain Postgres too, not just TimescaleDB's native policy).",
    ),
    SettingDef(
        key="retention.default_deadband_percent",
        category="Data Retention & Compression",
        label="Default deadband (% of engineering range)",
        type="float",
        default=0.0,
        min=0.0,
        max=50.0,
        description="Applied to tags that don't set their own deadband_percent. 0 disables deadband compression by default.",
    ),
    SettingDef(
        key="alarms.require_acknowledgment",
        category="Alarms",
        label="Require operator acknowledgment",
        type="bool",
        default=False,
        description="ISA-18.2 style: when on, the dashboard flags active/cleared alarms as needing an explicit Ack until an operator acknowledges them.",
    ),
    SettingDef(
        key="security.access_token_expire_minutes",
        category="Security",
        label="Session token lifetime (minutes)",
        type="int",
        default=480,
        min=5,
        max=10080,
        description="How long a login stays valid. Applies to tokens issued after this is changed; existing sessions keep their original expiry.",
    ),
    SettingDef(
        key="opcua_server.enabled",
        category="Embedded OPC UA Server",
        label="Enable embedded OPC UA server",
        type="bool",
        default=False,
        description="Host this instance's own OPC UA server so other SCADA/historian systems can connect to Ackiologs as a data source, instead of (or in addition to) Ackiologs connecting out to PLCs.",
    ),
    SettingDef(
        key="opcua_server.port",
        category="Embedded OPC UA Server",
        label="Port",
        type="int",
        default=4841,
        min=1,
        max=65535,
        description="TCP port for the embedded OPC UA server endpoint (opc.tcp://host:port/ackiologs/server/).",
    ),
    SettingDef(
        key="opcua_server.require_auth",
        category="Embedded OPC UA Server",
        label="Require login",
        type="bool",
        default=True,
        description="If on, OPC UA clients must authenticate with a valid Ackiologs username/password. If off, anonymous read access is allowed.",
    ),
    SettingDef(
        key="modbus_server.enabled",
        category="Embedded Modbus Server",
        label="Enable embedded Modbus TCP server",
        type="bool",
        default=False,
        description="Host this instance as a Modbus TCP server so PLCs/SCADA/HMIs that only "
        "speak Modbus can read Ackiologs' live tag values, instead of (or in addition to) "
        "Ackiologs polling Modbus devices itself. Read-only by design: tags are exposed as "
        "input registers/discrete inputs, which the Modbus protocol has no write function "
        "code for.",
    ),
    SettingDef(
        key="modbus_server.port",
        category="Embedded Modbus Server",
        label="Port",
        type="int",
        default=5020,
        min=1,
        max=65535,
        description="TCP port for the embedded Modbus server. Defaults to 5020, not the "
        "standard 502, since binding 502 requires elevated/root privileges on Linux; set it "
        "to 502 explicitly if this instance runs with that privilege.",
    ),
    SettingDef(
        key="display.time_format",
        category="Display",
        label="Time format",
        type="enum",
        default="24h",
        choices=("24h", "12h"),
        description="How the dashboard renders clock times.",
    ),
    SettingDef(
        key="display.language",
        category="Display",
        label="Default language",
        type="enum",
        default="en",
        choices=("en", "es", "fr", "de", "pt", "zh"),
        description="The dashboard's language for users who haven't picked their own from the "
        "language selector (top right of the header, and on the login screen).",
    ),
]

SETTINGS_BY_KEY: dict[str, SettingDef] = {s.key: s for s in SETTINGS}


def categories() -> list[str]:
    seen: dict[str, None] = {}
    for s in SETTINGS:
        seen.setdefault(s.category, None)
    return list(seen)
