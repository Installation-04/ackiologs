"""Filesystem locations that differ depending on how Ackiologs is running:
from source (`uvicorn app.main:app`, tests), or as a PyInstaller-frozen
executable (the Linux binary / Windows exe / MSI install). Everything else
in the app should go through these instead of hardcoding relative paths."""

from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def app_root() -> Path:
    """Directory the user's `config/` and `data/` live next to: the executable's
    folder when frozen, the repo root when running from source."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def bundled_static_dir() -> Path:
    """The dashboard's static files: bundled inside the frozen executable
    (PyInstaller extracts to sys._MEIPASS), or app/web/static on disk."""
    if is_frozen() and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "app" / "web" / "static"
    return Path(__file__).resolve().parent / "web" / "static"


def default_data_dir() -> Path:
    return app_root() / "data"


def default_config_dir() -> Path:
    return app_root() / "config"


def sqlite_file_path(database_url: str) -> Path | None:
    """The filesystem path a `sqlite(+driver):///...` URL points at, or None for
    any other backend (Postgres/TimescaleDB). Used to make sure that directory
    exists before SQLAlchemy tries to open it — important once the DB location is
    overridden away from default_data_dir(), e.g. by the Windows MSI installer."""
    if not database_url.startswith("sqlite"):
        return None
    raw = database_url.split("///", 1)[1]
    return Path(raw) if raw.startswith("/") else Path.cwd() / raw
