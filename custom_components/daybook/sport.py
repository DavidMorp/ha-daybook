"""Suggest sport entries from time spent in a zone.

Each sport place is an HA zone plus a person. A stay becomes a draft sport
entry when it overlaps the place's time windows (or the "on" periods of an HA
Schedule helper) for at least the minimum time. With no windows and no
schedule, the whole stay counts. Drafts show up in the panel to confirm or
dismiss, and optionally as a phone notification with Yes and No buttons.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from homeassistant.const import STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import CALLBACK_TYPE, Event, EventStateChangedData, callback
from homeassistant.helpers.event import async_track_state_change_event

from .const import KIND_SPORT, NOTIFY_ACTION_PREFIX, STATUS_CONFIRMED, STATUS_DRAFT, STATUS_REJECTED

if TYPE_CHECKING:
    from .data import DaybookData

_LOGGER = logging.getLogger(__name__)
KV_OPEN = "sport_open"


def _hm(value: str) -> tuple[int, int]:
    h, m = value.split(":")
    return int(h), int(m)


def window_overlap_seconds(start: float, end: float, windows: list[dict[str, Any]], tz: ZoneInfo) -> float:
    """Seconds of [start, end] inside the weekly windows. Windows may cross midnight."""
    if end <= start:
        return 0.0
    total = 0.0
    first = datetime.fromtimestamp(start, tz).date() - timedelta(days=1)
    last = datetime.fromtimestamp(end, tz).date()
    day = first
    while day <= last:
        for w in windows:
            if day.weekday() not in w["weekdays"]:
                continue
            fh, fm = _hm(w["from"])
            th, tm = _hm(w["to"])
            w_start = datetime(day.year, day.month, day.day, fh, fm, tzinfo=tz)
            w_end = datetime(day.year, day.month, day.day, th, tm, tzinfo=tz)
            if w_end <= w_start:
                w_end += timedelta(days=1)
            overlap = min(end, w_end.timestamp()) - max(start, w_start.timestamp())
            if overlap > 0:
                total += overlap
        day += timedelta(days=1)
    return total


class SportTracker:
    def __init__(self, data: DaybookData) -> None:
        self.data = data
        self.hass = data.hass
        self._unsubs: list[CALLBACK_TYPE] = []
        # zone id -> {"start": ts, "sched_s": seconds with schedule on, "sched_since": ts|None}
        self._open: dict[str, dict[str, Any]] = {}

    @property
    def zones(self) -> list[dict[str, Any]]:
        return self.data.settings["sport_zones"]

    async def async_start(self) -> None:
        stored = await self.hass.async_add_executor_job(self.data.store.kv_get, KV_OPEN, {}) or {}
        self._open = {k: v for k, v in stored.items() if isinstance(v, dict)}
        persons = sorted({z["person"] for z in self.zones})
        schedules = sorted({z["schedule"] for z in self.zones if z.get("schedule")})
        if persons:
            self._unsubs.append(async_track_state_change_event(self.hass, persons, self._person_changed))
        if schedules:
            self._unsubs.append(async_track_state_change_event(self.hass, schedules, self._schedule_changed))
        self._unsubs.append(self.hass.bus.async_listen("mobile_app_notification_action", self._notify_action))
        now = time.time()
        for z in self.zones:
            state = self.hass.states.get(z["person"])
            if state and self._in_zone(state.state, z) and z["id"] not in self._open:
                self._open[z["id"]] = self._new_stay(z, now)
            elif z["id"] in self._open and not (state and self._in_zone(state.state, z)):
                # Left while Home Assistant was down; we don't know when, so drop it.
                self._open.pop(z["id"])
        await self._save()

    @callback
    def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

    def _schedule_on(self, z: dict[str, Any]) -> bool:
        state = self.hass.states.get(z["schedule"]) if z.get("schedule") else None
        return bool(state and state.state == STATE_ON)

    def _new_stay(self, z: dict[str, Any], now: float) -> dict[str, Any]:
        return {"start": now, "sched_s": 0.0, "sched_since": now if self._schedule_on(z) else None}

    def _in_zone(self, person_state: str, z: dict[str, Any]) -> bool:
        zone = self.hass.states.get(z["zone"])
        if zone is None:
            return False
        names = {zone.name.lower(), z["zone"].split(".", 1)[1].replace("_", " ")}
        if z["zone"] == "zone.home":
            names.add("home")
        return person_state.lower() in names

    async def _save(self) -> None:
        await self.hass.async_add_executor_job(self.data.store.kv_set, KV_OPEN, self._open)

    async def _schedule_changed(self, event: Event[EventStateChangedData]) -> None:
        now = time.time()
        on = bool(event.data["new_state"] and event.data["new_state"].state == STATE_ON)
        for z in self.zones:
            stay = self._open.get(z["id"])
            if not stay or z.get("schedule") != event.data["entity_id"]:
                continue
            if on and stay["sched_since"] is None:
                stay["sched_since"] = now
            elif not on and stay["sched_since"] is not None:
                stay["sched_s"] += now - stay["sched_since"]
                stay["sched_since"] = None
        await self._save()

    async def _person_changed(self, event: Event[EventStateChangedData]) -> None:
        new = event.data["new_state"]
        if new is None or new.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return
        now = time.time()
        for z in self.zones:
            if z["person"] != event.data["entity_id"]:
                continue
            inside = self._in_zone(new.state, z)
            if inside and z["id"] not in self._open:
                self._open[z["id"]] = self._new_stay(z, now)
            elif not inside and z["id"] in self._open:
                await self._finish(z, self._open.pop(z["id"]), now)
        await self._save()

    def qualifying_seconds(self, z: dict[str, Any], stay: dict[str, Any], end: float) -> float:
        if z.get("schedule"):
            extra = end - stay["sched_since"] if stay.get("sched_since") is not None else 0.0
            return stay["sched_s"] + extra
        if z.get("windows"):
            return window_overlap_seconds(stay["start"], end, z["windows"], self.data.tz)
        return end - stay["start"]

    async def _finish(self, z: dict[str, Any], stay: dict[str, Any], ended: float) -> None:
        if self.qualifying_seconds(z, stay, ended) < z.get("min_minutes", 60) * 60:
            return
        entry = await self.data.async_add({
            "kind": KIND_SPORT,
            "item": z["activity"],
            "start": stay["start"],
            "end": ended,
            "status": STATUS_DRAFT,
            "source": f"zone:{z['id']}",
        })
        await self._notify(entry, (ended - stay["start"]) / 60)

    async def _notify(self, entry: dict[str, Any], minutes: float) -> None:
        service = self.data.settings.get("notify_service")
        if not service or not self.hass.services.has_service("notify", service):
            return
        hours, mins = divmod(int(minutes), 60)
        length = f"{hours} h {mins} min" if hours else f"{mins} min"
        try:
            await self.hass.services.async_call("notify", service, {
                "title": "Daybook",
                "message": f"Log {entry['item'].lower()}? {length}",
                "data": {
                    "tag": f"daybook_{entry['id']}",
                    "actions": [
                        {"action": f"{NOTIFY_ACTION_PREFIX}CONFIRM_{entry['id']}", "title": "Yes"},
                        {"action": f"{NOTIFY_ACTION_PREFIX}REJECT_{entry['id']}", "title": "No"},
                    ],
                },
            })
        except Exception:  # noqa: BLE001 - a failed notification must not lose the entry
            _LOGGER.warning("Could not send the Daybook sport notification", exc_info=True)

    async def _notify_action(self, event: Event) -> None:
        action = event.data.get("action", "")
        if not action.startswith(NOTIFY_ACTION_PREFIX):
            return
        verb, _, entry_id = action[len(NOTIFY_ACTION_PREFIX):].partition("_")
        status = {"CONFIRM": STATUS_CONFIRMED, "REJECT": STATUS_REJECTED}.get(verb)
        if not status or not entry_id:
            return
        current = await self.hass.async_add_executor_job(self.data.store.get, entry_id)
        if current and current["status"] == STATUS_DRAFT:
            await self.data.async_update(entry_id, {"status": status})
