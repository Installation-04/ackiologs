"""Loads config/connections.yaml and config/tags.yaml — the declarative definition of
what to collect and from where. Editing these files and restarting (or POSTing to
/api/config/reload) is the whole "configure a new tag" workflow."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_ENV_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


@dataclass
class ConnectionSpec:
    name: str
    protocol: str
    config: dict[str, Any] = field(default_factory=dict)


@dataclass
class TagSpec:
    name: str
    connection: str
    address: str
    data_type: str = "float"
    engineering_units: str | None = None
    min_value: float | None = None
    max_value: float | None = None
    deadband_percent: float | None = None
    description: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    alarms: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class HistorianConfig:
    connections: list[ConnectionSpec]
    tags: list[TagSpec]

    def tags_by_connection(self, connection_name: str) -> list[TagSpec]:
        return [t for t in self.tags if t.connection == connection_name]


_KNOWN_TAG_FIELDS = {
    "name",
    "connection",
    "address",
    "data_type",
    "engineering_units",
    "min_value",
    "max_value",
    "deadband_percent",
    "description",
    "alarms",
}


def load_config(connections_path: Path, tags_path: Path) -> HistorianConfig:
    connections_raw = _read_yaml(connections_path).get("connections", [])
    tags_raw = _read_yaml(tags_path).get("tags", [])

    connections = [
        ConnectionSpec(
            name=c["name"],
            protocol=c["protocol"],
            config={k: v for k, v in c.items() if k not in ("name", "protocol")},
        )
        for c in connections_raw
    ]

    tags = []
    for t in tags_raw:
        extra = {k: v for k, v in t.items() if k not in _KNOWN_TAG_FIELDS}
        tags.append(
            TagSpec(
                name=t["name"],
                connection=t["connection"],
                address=t.get("address", ""),
                data_type=t.get("data_type", "float"),
                engineering_units=t.get("engineering_units"),
                min_value=t.get("min_value"),
                max_value=t.get("max_value"),
                deadband_percent=t.get("deadband_percent"),
                description=t.get("description"),
                extra=extra,
                alarms=t.get("alarms", []),
            )
        )

    return HistorianConfig(connections=connections, tags=tags)


def _read_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        raw = fh.read()
    expanded = _ENV_VAR_RE.sub(lambda m: os.environ.get(m.group(1), ""), raw)
    return yaml.safe_load(expanded) or {}


def tag_spec_to_connector_dict(tag: TagSpec) -> dict[str, Any]:
    """The shape connectors expect: name/address/data_type plus any protocol-specific
    extras (e.g. `sim:` block for the simulator)."""
    d = {
        "name": tag.name,
        "address": tag.address,
        "data_type": tag.data_type,
    }
    d.update(tag.extra)
    return d
