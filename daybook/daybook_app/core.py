"""The journal: entries, settings and derived values, independent of transport."""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from collections.abc import Callable
from datetime import tzinfo
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from . import insights
from .const import KIND_INTAKE, KIND_STATE
from .model import doses, amount_at, level_at
from .settings import all_items, merge_defaults, validate
from .store import DaybookStore, StoreError

_LOGGER = logging.getLogger(__name__)
SETTINGS_KEY = "settings"

Listener = Callable[[str, dict[str, Any] | None], Any]


class JournalError(ValueError):
    """A request that can't be carried out, with a message for people."""


class Journal:
    def __init__(self, data_dir: str | Path, tz_name: str | None = None) -> None:
        self.store = DaybookStore(str(Path(data_dir) / "daybook.db"))
        self.settings: dict[str, Any] = merge_defaults(None)
        self._listeners: list[Listener] = []
        self.set_time_zone(tz_name)

    def set_time_zone(self, tz_name: str | None) -> None:
        try:
            self.tz: tzinfo = ZoneInfo(tz_name) if tz_name else _local_tz()
        except Exception:  # noqa: BLE001 - unknown name: fall back to local time
            self.tz = _local_tz()

    async def start(self) -> None:
        await asyncio.to_thread(self.store.open)
        stored = await asyncio.to_thread(self.store.kv_get, SETTINGS_KEY)
        self.settings = validate(stored) if stored else validate({})
        if stored and stored != self.settings:
            # Saves settings converted from an older version, once.
            await asyncio.to_thread(self.store.kv_set, SETTINGS_KEY, self.settings)

    async def stop(self) -> None:
        await asyncio.to_thread(self.store.close)

    # -- change notifications -----------------------------------------
    def on_change(self, listener: Listener) -> Callable[[], None]:
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener) if listener in self._listeners else None

    async def _emit(self, what: str, entry: dict[str, Any] | None = None) -> None:
        for listener in list(self._listeners):
            try:
                result = listener(what, entry)
                if inspect.isawaitable(result):
                    await result
            except Exception:  # noqa: BLE001 - one broken listener must not stop logging
                _LOGGER.exception("Change listener failed")

    # -- settings -------------------------------------------------------
    async def set_settings(self, new: dict[str, Any]) -> dict[str, Any]:
        try:
            settings = validate(new)
        except Exception as err:  # voluptuous errors
            raise JournalError(f"Settings not saved: {err}") from err
        await asyncio.to_thread(self.store.kv_set, SETTINGS_KEY, settings)
        self.settings = settings
        await self._emit("settings")
        return settings

    def item(self, item_id: str | None) -> dict[str, Any] | None:
        return next((i for i in all_items(self.settings) if i["id"] == item_id), None)

    # -- entries --------------------------------------------------------
    def _prepare(self, entry: dict[str, Any]) -> dict[str, Any]:
        kind = entry.get("kind")
        value = dict(entry.get("value") or {})
        if kind == KIND_STATE:
            if not any(s["id"] == entry.get("item") for s in self.settings["states"]):
                raise JournalError(f"There's no state called \"{entry.get('item')}\" in Settings.")
        if kind == KIND_INTAKE:
            item = self.item(entry.get("item"))
            if item is None:
                raise JournalError(f"There's nothing called \"{entry.get('item')}\" in Settings.")
            if value.get("amount") is None and item.get("amount") is not None:
                value["amount"] = item["amount"]
            value.setdefault("unit", item.get("unit", ""))
        entry["value"] = value
        return entry

    async def add(self, entry: dict[str, Any]) -> dict[str, Any]:
        entry = self._prepare(dict(entry))
        entry.setdefault("start", time.time())
        try:
            saved = await asyncio.to_thread(self.store.add, entry)
        except StoreError as err:
            raise JournalError(str(err)) from err
        await self._emit("added", saved)
        return saved

    async def get(self, entry_id: str) -> dict[str, Any] | None:
        return await asyncio.to_thread(self.store.get, entry_id)

    async def update(self, entry_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        current = await self.get(entry_id)
        if current is None:
            raise JournalError(f"There's no entry with id {entry_id}.")
        if {"item", "value"} & set(changes):
            probe = self._prepare({**current, **changes})
            changes = {**changes, "value": probe["value"]}
        try:
            saved = await asyncio.to_thread(self.store.update, entry_id, changes)
        except StoreError as err:
            raise JournalError(str(err)) from err
        await self._emit("updated", saved)
        return saved

    async def delete(self, entry_id: str) -> dict[str, Any]:
        try:
            saved = await asyncio.to_thread(self.store.delete, entry_id)
        except StoreError as err:
            raise JournalError(str(err)) from err
        await self._emit("deleted", saved)
        return saved

    async def restore(self, entry_id: str) -> dict[str, Any]:
        try:
            saved = await asyncio.to_thread(self.store.restore, entry_id)
        except StoreError as err:
            raise JournalError(str(err)) from err
        await self._emit("restored", saved)
        return saved

    async def undo_last(self, source: str | None, within_minutes: int = 10) -> dict[str, Any] | None:
        since = time.time() - within_minutes * 60
        last = await asyncio.to_thread(self.store.last_by_source, source, since)
        return await self.delete(last["id"]) if last else None

    async def list(self, start: float | None = None, end: float | None = None, **kw: Any) -> list[dict[str, Any]]:
        return await asyncio.to_thread(lambda: self.store.list(start, end, **kw))

    async def history(self, entry_id: str) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self.store.history, entry_id)

    # -- derived --------------------------------------------------------
    async def level_now(self, substance_id: str) -> dict[str, float]:
        now = time.time()
        entries = await self.list(now - 4 * 86400, now, kinds=[KIND_INTAKE])
        d = doses(entries, self.settings, substance_id)
        return {
            "amount": amount_at(d, now, self.settings, substance_id),
            "level": level_at(d, now, self.settings, substance_id),
        }

    async def insights(self, days: int) -> dict[str, Any]:
        end = time.time()
        entries = await self.list(end - days * 86400 - 86400, end)
        return await asyncio.to_thread(insights.compute, entries, self.settings, self.tz)


def _local_tz() -> tzinfo:
    from datetime import datetime
    return datetime.now().astimezone().tzinfo  # type: ignore[return-value]
