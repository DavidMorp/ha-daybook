"""Runtime object shared by the actions, the panel API and the entities."""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.dispatcher import async_dispatcher_send

from . import insights
from .const import (
    DOMAIN,
    EVENT_LOGGED,
    KIND_CAFFEINE,
    KIND_MED,
    KIND_STATE,
    MED_SKIPPED,
    MED_TAKEN,
    SIGNAL_CHANGED,
)
from .model import caffeine_at, caffeine_doses
from .settings import merge_defaults, validate
from .store import DaybookStore, StoreError

SETTINGS_KEY = "settings"


class DaybookData:
    """Holds the store and settings for the single Daybook entry."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, store: DaybookStore) -> None:
        self.hass = hass
        self.entry = entry
        self.store = store
        self.settings: dict[str, Any] = merge_defaults(None)
        self.sport: Any = None

    async def async_load(self) -> None:
        stored = await self.hass.async_add_executor_job(self.store.kv_get, SETTINGS_KEY)
        self.settings = merge_defaults(stored)

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.hass.config.time_zone)

    # -- settings ------------------------------------------------------
    async def async_set_settings(self, new: dict[str, Any]) -> dict[str, Any]:
        settings = validate(new)
        old = self.settings
        await self.hass.async_add_executor_job(self.store.kv_set, SETTINGS_KEY, settings)
        self.settings = settings
        self._changed("settings")
        if repr(old["sport_zones"]) != repr(settings["sport_zones"]) and self.sport is not None:
            # Restart only the sport tracker; no need to reload the entities.
            self.sport.async_stop()
            await self.sport.async_start()
        if self._entities_changed(old, settings):
            self.hass.config_entries.async_schedule_reload(self.entry.entry_id)
        return settings

    @staticmethod
    def _entities_changed(old: dict, new: dict) -> bool:
        def key(s: dict) -> tuple:
            return (
                tuple((x["id"], x["name"]) for x in s["states"]),
                tuple((x["id"], x["name"]) for x in s["drinks"]),
                tuple((x["id"], x["name"]) for x in s["meds"]),
                s["caffeine_sensor"],
            )
        return key(old) != key(new)

    def item_def(self, kind: str, item: str | None) -> dict[str, Any] | None:
        group = {KIND_STATE: "states", KIND_CAFFEINE: "drinks", KIND_MED: "meds"}.get(kind)
        if not group or item is None:
            return None
        return next((x for x in self.settings[group] if x["id"] == item), None)

    # -- entries -------------------------------------------------------
    def _prepare(self, entry: dict[str, Any]) -> dict[str, Any]:
        """Fill defaults from settings and check items exist."""
        kind = entry.get("kind")
        item = entry.get("item")
        value = dict(entry.get("value") or {})
        if kind in (KIND_STATE, KIND_CAFFEINE, KIND_MED):
            definition = self.item_def(kind, item)
            if definition is None:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="unknown_item",
                    translation_placeholders={"kind": str(kind), "item": str(item)},
                )
            if kind == KIND_CAFFEINE and "mg" not in value:
                value["mg"] = definition["mg"]
            if kind == KIND_MED:
                value.setdefault("status", MED_TAKEN)
                if value["status"] not in (MED_TAKEN, MED_SKIPPED):
                    raise ServiceValidationError(
                        translation_domain=DOMAIN, translation_key="bad_med_status"
                    )
                if value["status"] == MED_TAKEN and "dose" not in value and definition.get("dose") is not None:
                    value["dose"] = definition["dose"]
                    value["unit"] = definition.get("unit", "mg")
        entry["value"] = value
        return entry

    async def async_add(self, entry: dict[str, Any]) -> dict[str, Any]:
        entry = self._prepare(dict(entry))
        try:
            saved = await self.hass.async_add_executor_job(self.store.add, entry)
        except StoreError as err:
            raise ServiceValidationError(str(err)) from err
        self.hass.bus.async_fire(
            EVENT_LOGGED,
            {"id": saved["id"], "kind": saved["kind"], "item": saved["item"],
             "status": saved["status"], "source": saved["source"]},
        )
        self._changed("entries")
        return saved

    async def async_update(self, entry_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        current = await self.hass.async_add_executor_job(self.store.get, entry_id)
        if current is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="unknown_entry",
                translation_placeholders={"id": entry_id},
            )
        if "kind" in changes or "item" in changes or "value" in changes:
            probe = {**current, **changes}
            self._prepare(probe)
            if "value" in changes or "item" in changes:
                changes = {**changes, "value": probe["value"]}
        try:
            saved = await self.hass.async_add_executor_job(self.store.update, entry_id, changes)
        except StoreError as err:
            raise ServiceValidationError(str(err)) from err
        self._changed("entries")
        return saved

    async def async_delete(self, entry_id: str) -> dict[str, Any]:
        try:
            saved = await self.hass.async_add_executor_job(self.store.delete, entry_id)
        except StoreError as err:
            raise ServiceValidationError(str(err)) from err
        self._changed("entries")
        return saved

    async def async_restore(self, entry_id: str) -> dict[str, Any]:
        try:
            saved = await self.hass.async_add_executor_job(self.store.restore, entry_id)
        except StoreError as err:
            raise ServiceValidationError(str(err)) from err
        self._changed("entries")
        return saved

    async def async_undo_last(self, source: str | None, within_minutes: int) -> dict[str, Any] | None:
        since = time.time() - within_minutes * 60
        last = await self.hass.async_add_executor_job(self.store.last_by_source, source, since)
        if last is None:
            return None
        return await self.async_delete(last["id"])

    async def async_list(self, start: float | None, end: float | None, **kw: Any) -> list[dict]:
        return await self.hass.async_add_executor_job(
            lambda: self.store.list(start, end, **kw)
        )

    # -- derived -------------------------------------------------------
    async def async_caffeine_now(self) -> float:
        now = time.time()
        entries = await self.async_list(now - 36 * 3600, now, kinds=[KIND_CAFFEINE])
        return caffeine_at(
            caffeine_doses(entries), now,
            self.settings["caffeine_half_life_h"], self.settings["caffeine_absorption_min"],
        )

    async def async_insights(self, days: int) -> dict[str, Any]:
        end = time.time()
        start = end - days * 86400
        entries = await self.async_list(start - 86400, end)
        settings = self.settings
        tz = self.tz
        return await self.hass.async_add_executor_job(insights.compute, entries, settings, tz)

    def day_bounds(self, day: datetime) -> tuple[float, float]:
        start = day.replace(hour=self.settings["day_start_hour"], minute=0, second=0, microsecond=0)
        return start.timestamp(), (start + timedelta(days=1)).timestamp()

    @callback
    def _changed(self, what: str) -> None:
        async_dispatcher_send(self.hass, SIGNAL_CHANGED, what)
