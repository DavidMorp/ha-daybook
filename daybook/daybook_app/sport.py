"""Suggest sport entries from time spent in a Home Assistant zone.

Each sport place is an HA zone plus a person. A stay becomes a draft sport
entry when it overlaps the place's time windows (or the "on" periods of an HA
Schedule helper) for at least the minimum time. With no windows and no
schedule, the whole stay counts. Drafts show up in the panel to confirm or
dismiss, and optionally as a phone notification with Yes and No buttons.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, tzinfo
from typing import TYPE_CHECKING, Any

from .const import KIND_SPORT, NOTIFY_ACTION_PREFIX, STATUS_CONFIRMED, STATUS_DRAFT, STATUS_REJECTED

if TYPE_CHECKING:
    from .core import Journal
    from .ha import HomeAssistantLink

_LOGGER = logging.getLogger(__name__)
KV_OPEN = "sport_open"
IGNORED = ("unavailable", "unknown", None)


def _hm(value: str) -> tuple[int, int]:
    h, m = value.split(":")
    return int(h), int(m)


def window_overlap_seconds(start: float, end: float, windows: list[dict[str, Any]], tz: tzinfo) -> float:
    """Seconds of [start, end] inside the weekly windows. Windows may cross midnight."""
    if end <= start:
        return 0.0
    total = 0.0
    day = datetime.fromtimestamp(start, tz).date() - timedelta(days=1)
    last = datetime.fromtimestamp(end, tz).date()
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
    def __init__(self, journal: Journal, ha: HomeAssistantLink) -> None:
        self.journal = journal
        self.ha = ha
        # zone id -> {"start": ts, "sched_s": seconds with schedule on, "sched_since": ts|None}
        self._open: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    @property
    def zones(self) -> list[dict[str, Any]]:
        return self.journal.settings["sport_zones"]

    async def start(self) -> None:
        stored = await asyncio.to_thread(self.journal.store.kv_get, KV_OPEN, {}) or {}
        self._open = {k: v for k, v in stored.items() if isinstance(v, dict)}
        self.ha.on_state.append(self.state_changed)
        self.ha.on_event.append(self.event)
        self.ha.on_connect.append(self.resync)
        self.journal.on_change(self._settings_changed)
        if self.ha.connected:
            await self.resync()

    async def _settings_changed(self, what: str, _entry: Any) -> None:
        if what == "settings":
            await self.resync()

    async def resync(self) -> None:
        """Match open stays to where people are now (after a restart or settings change)."""
        async with self._lock:
            now = time.time()
            ids = {z["id"] for z in self.zones}
            for zid in list(self._open):
                if zid not in ids:
                    self._open.pop(zid)
            for z in self.zones:
                state = (self.ha.states.get(z["person"]) or {}).get("state")
                if state in IGNORED:
                    continue
                inside = self._in_zone(state, z)
                if inside and z["id"] not in self._open:
                    self._open[z["id"]] = self._new_stay(z, now)
                elif not inside and z["id"] in self._open:
                    # Left while we weren't watching; we don't know when, so drop it.
                    self._open.pop(z["id"])
            await self._save()

    def _schedule_on(self, z: dict[str, Any]) -> bool:
        return bool(z.get("schedule")) and (self.ha.states.get(z["schedule"]) or {}).get("state") == "on"

    def _new_stay(self, z: dict[str, Any], now: float) -> dict[str, Any]:
        return {"start": now, "sched_s": 0.0, "sched_since": now if self._schedule_on(z) else None}

    def _in_zone(self, person_state: str, z: dict[str, Any]) -> bool:
        if z["zone"] not in self.ha.states:
            return False
        names = {self.ha.friendly_name(z["zone"]).lower(), z["zone"].split(".", 1)[1].replace("_", " ")}
        if z["zone"] == "zone.home":
            names.add("home")
        return person_state.lower() in names

    async def _save(self) -> None:
        await asyncio.to_thread(self.journal.store.kv_set, KV_OPEN, self._open)

    async def state_changed(self, entity_id: str, state: dict[str, Any] | None, now: float | None = None) -> None:
        now = time.time() if now is None else now
        new = (state or {}).get("state")
        async with self._lock:
            changed = False
            for z in self.zones:
                stay = self._open.get(z["id"])
                if z.get("schedule") == entity_id and stay:
                    if new == "on" and stay["sched_since"] is None:
                        stay["sched_since"] = now
                    elif new != "on" and stay["sched_since"] is not None:
                        stay["sched_s"] += now - stay["sched_since"]
                        stay["sched_since"] = None
                    changed = True
                if z["person"] != entity_id or new in IGNORED:
                    continue
                inside = self._in_zone(new, z)
                if inside and not stay:
                    self._open[z["id"]] = self._new_stay(z, now)
                    changed = True
                elif not inside and stay:
                    self._open.pop(z["id"])
                    changed = True
                    await self._finish(z, stay, now)
            if changed:
                await self._save()

    def qualifying_seconds(self, z: dict[str, Any], stay: dict[str, Any], end: float) -> float:
        if z.get("schedule"):
            extra = end - stay["sched_since"] if stay.get("sched_since") is not None else 0.0
            return stay["sched_s"] + extra
        if z.get("windows"):
            return window_overlap_seconds(stay["start"], end, z["windows"], self.journal.tz)
        return end - stay["start"]

    async def _finish(self, z: dict[str, Any], stay: dict[str, Any], ended: float) -> None:
        if self.qualifying_seconds(z, stay, ended) < z.get("min_minutes", 60) * 60:
            return
        entry = await self.journal.add({
            "kind": KIND_SPORT,
            "item": z["activity"],
            "start": stay["start"],
            "end": ended,
            "status": STATUS_DRAFT,
            "source": f"zone:{z['id']}",
        })
        await self._notify(entry, (ended - stay["start"]) / 60)

    async def _notify(self, entry: dict[str, Any], minutes: float) -> None:
        service = self.journal.settings.get("notify_service")
        if not service or not self.ha.connected:
            return
        hours, mins = divmod(int(minutes), 60)
        length = f"{hours} h {mins} min" if hours else f"{mins} min"
        try:
            await self.ha.call_service("notify", service, {
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
            _LOGGER.warning("Could not send the sport notification", exc_info=True)

    async def event(self, event_type: str, data: dict[str, Any]) -> None:
        if event_type != "mobile_app_notification_action":
            return
        action = data.get("action", "")
        if not action.startswith(NOTIFY_ACTION_PREFIX):
            return
        verb, _, entry_id = action[len(NOTIFY_ACTION_PREFIX):].partition("_")
        status = {"CONFIRM": STATUS_CONFIRMED, "REJECT": STATUS_REJECTED}.get(verb)
        if not status or not entry_id:
            return
        current = await self.journal.get(entry_id)
        if current and current["status"] == STATUS_DRAFT:
            await self.journal.update(entry_id, {"status": status})
