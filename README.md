# Ackiologs

A protocol-agnostic industrial data historian. Collect time-series data from PLCs,
SCADA systems and IIoT gateways over OPC UA, Modbus, and MQTT; store it in SQLite
(zero-config) or TimescaleDB (production scale); trend it, alarm on it, and expose
it over a REST/WebSocket API and a built-in dashboard.

## Features

- **Multi-protocol ingestion** — OPC UA (subscriptions), Modbus TCP/RTU (polling),
  MQTT (plain or JSON-path/Sparkplug-style payloads), and a built-in Simulator for
  demos and tests. The connector interface (`app/connectors/base.py`) is small —
  adding BACnet/IP, DNP3, EtherNet/IP-CIP, or a vendor cloud API is one new class.
- **Pluggable storage** — SQLite by default (nothing to install), or Postgres +
  TimescaleDB for production (auto-creates the hypertable and, optionally, a
  retention policy).
- **Deadband compression** — per-tag or global percent-of-range deadband so noisy
  signals don't flood storage.
- **Alarming** — high/high-high/low/low-low/digital/bad-quality conditions defined
  per tag in config, with a full alarm & event journal (activate/clear history).
- **Live dashboard** — real-time value table over WebSocket, historical trend
  charts (raw or time-bucketed), alarm log, and connection health — no build step,
  served directly by the API.
- **REST + WebSocket API** — tags, history (raw & aggregated), live streaming,
  connection health, alarm events, and tag writes (setpoints) — see `/docs` for
  interactive OpenAPI docs once running.
- **JWT auth with roles** (admin/operator/viewer); disable for isolated demo/dev use.
- **Config-as-code** — `config/connections.yaml` and `config/tags.yaml` fully
  define what's collected; edit and `POST /api/config/reload`, or restart.
- **Deploys in one command** — Docker Compose, SQLite by default, TimescaleDB as
  a one-line overlay.

## Quickstart (Docker — recommended)

```bash
docker compose up -d
```

Open http://localhost:8000. The first boot creates a default `admin` user with a
random password — check the container logs for it:

```bash
docker compose logs historian | grep "Created default admin"
```

It ships with the Simulator connection enabled, so you'll see live trending data
immediately with no field equipment required.

### With TimescaleDB (production-scale storage)

```bash
docker compose -f docker-compose.yml -f docker-compose.timescale.yml up -d
```

This adds a TimescaleDB container and points the historian at it — `tag_values`
is automatically converted into a hypertable on startup.

## Quickstart (local, no Docker)

```bash
./scripts/quickstart.sh
```

Creates a venv, installs dependencies, and runs the app with SQLite at
http://localhost:8000.

## Configuring data collection

Edit `config/connections.yaml` (where to connect) and `config/tags.yaml` (what to
collect), then either restart or call:

```bash
curl -X POST http://localhost:8000/api/config/reload -H "Authorization: Bearer $TOKEN"
```

New connections need a restart; tag/alarm edits on existing connections apply on reload.

### Tag address formats

| Protocol  | `address` format                                  | Example                                  |
|-----------|----------------------------------------------------|-------------------------------------------|
| OPC UA    | UA NodeId string                                    | `ns=2;s=Pump3.Pressure`                  |
| Modbus    | `<table>:<register>[:<encoding>]`                   | `holding:40001:float32`, `coil:5`        |
| MQTT      | topic, or `json:<topic>:<dotted.key.path>`          | `json:plant/line1/telemetry:temperature` |
| Simulator | unused; behavior set by the tag's `sim:` block      | `sine`, `random_walk`, `counter`, `bool_toggle` |

Modbus tables: `holding`, `input`, `coil`, `discrete_input`. Register encodings
(holding/input only): `int16` (default), `uint16`, `int32`, `uint32`, `float32`.

## Adding a protocol

Subclass `app.connectors.base.BaseConnector`, implement `async def run(self)` to
connect and call `await self.emit(tag_name, value, quality=...)` for each sample,
and register the class in `app/connectors/registry.py`. Nothing else in the
system — storage, API, dashboard, alarms — needs to change.

## API

Interactive docs at `/docs` once running. Highlights:

- `POST /api/auth/token` — login, returns a JWT.
- `GET /api/tags` — all tags with current live value.
- `GET /api/history/{tag}?start=...&end=...&interval_seconds=...` — raw samples
  (`interval_seconds=0`) or time-bucketed avg/min/max/count.
- `WS /ws/live` — live value stream, all tags.
- `POST /api/tags/{tag}/write` — write a value back to the field device
  (operator/admin role; supported protocols only).
- `GET /api/connections` — connector health.
- `GET /api/alarms/events` — alarm/event journal.

## Architecture

```
connectors (OPC UA / Modbus / MQTT / Simulator / ...)
        │  Sample(tag, value, ts, quality)
        ▼
   asyncio.Queue
        │
        ▼
 ingest pipeline  ──► live bus (WebSocket, current-value cache)
        │           ──► alarm evaluation (alarm & event journal)
        ▼  (deadband-filtered, batched)
   SQLite / TimescaleDB
        ▲
        │
   REST / WebSocket API ──► dashboard (static HTML/JS)
```

## Configuration reference

All settings are environment variables prefixed `ACKIOLOGS_` (see `app/config.py`
and `.env.example`), including `DATABASE_URL`, `SECRET_KEY`, `AUTH_ENABLED`, and
`RETENTION_DAYS`.

## Development

```bash
pip install -e ".[dev]"
pytest
```
