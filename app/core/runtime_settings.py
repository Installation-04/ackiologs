"""In-memory cache + DB persistence for runtime-editable settings. A module-level
singleton (`runtime_settings`), same pattern as `app.ingest.live.live_bus` —
cheap synchronous reads for the hot paths (deadband check, token creation)
after an async `load()` at startup, with writes going through `set_many()`."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.core.settings_registry import SETTINGS, SETTINGS_BY_KEY
from app.db.base import session_scope
from app.db.models import AppSetting


class RuntimeSettings:
    def __init__(self) -> None:
        self._cache: dict[str, Any] = {s.key: s.default for s in SETTINGS}

    async def load(self, seed: dict[str, Any] | None = None) -> None:
        """Load persisted settings, then (only for keys with no saved row yet —
        i.e. first boot) apply `seed` values, typically sourced from the
        corresponding ACKIOLOGS_* env var so that variable still sets the initial
        value. Once a setting has been saved via the Settings page, its DB row
        takes over and the env var is ignored on subsequent restarts."""
        async with session_scope() as session:
            rows = (await session.execute(select(AppSetting))).scalars().all()
        existing_keys = {row.key for row in rows}
        for row in rows:
            setting_def = SETTINGS_BY_KEY.get(row.key)
            if setting_def is None:
                continue  # a setting removed from the registry since this was saved
            try:
                self._cache[row.key] = setting_def.coerce(row.value)
            except ValueError:
                pass  # corrupted/stale value — keep the default rather than crash startup

        if seed:
            to_persist = {k: v for k, v in seed.items() if k not in existing_keys}
            if to_persist:
                await self.set_many(to_persist)

    def get(self, key: str) -> Any:
        return self._cache.get(key, SETTINGS_BY_KEY[key].default)

    def all(self) -> dict[str, Any]:
        return dict(self._cache)

    async def set_many(self, updates: dict[str, Any]) -> list[str]:
        """Validate and persist updates; returns the list of keys that actually
        changed value (callers use this to decide what needs to be re-applied
        live, e.g. restarting the embedded OPC UA server)."""
        changed: list[str] = []
        async with session_scope() as session:
            for key, value in updates.items():
                setting_def = SETTINGS_BY_KEY.get(key)
                if setting_def is None:
                    raise ValueError(f"unknown setting '{key}'")
                setting_def.validate(value)
                if self._cache.get(key) != value:
                    changed.append(key)
                str_value = setting_def.to_str(value)
                existing = await session.get(AppSetting, key)
                if existing is not None:
                    existing.value = str_value
                else:
                    session.add(AppSetting(key=key, value=str_value))
                self._cache[key] = value
            await session.commit()
        return changed


runtime_settings = RuntimeSettings()
