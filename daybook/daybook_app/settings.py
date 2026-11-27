"""Settings schema. Settings live in the Daybook database, edited from the panel."""

from __future__ import annotations

import copy
import re
from typing import Any

import voluptuous as vol

from .const import DEFAULT_SETTINGS, ENERGY_HIGH, ENERGY_LOW, ENERGY_NEUTRAL
from .substances import PROFILES

_ID = vol.All(str, vol.Match(r"^[a-z0-9_]{1,40}$"))
_COLOR = vol.All(str, vol.Match(r"^#[0-9a-fA-F]{6}$"))
_TIME = vol.All(str, vol.Match(r"^([01]\d|2[0-3]):[0-5]\d$"))
_NAME = vol.All(str, vol.Length(min=1, max=60))
_PROFILE = vol.In(list(PROFILES))
_HOURS = vol.All(vol.Coerce(float), vol.Range(min=0, max=48))

STATE_SCHEMA = vol.Schema({
    vol.Required("id"): _ID,
    vol.Required("name"): _NAME,
    vol.Required("color"): _COLOR,
    vol.Required("energy"): vol.In([ENERGY_HIGH, ENERGY_LOW, ENERGY_NEUTRAL]),
})
ITEM_SCHEMA = vol.Schema({
    vol.Required("id"): _ID,
    vol.Required("name"): _NAME,
    vol.Optional("amount", default=None): vol.Any(None, vol.All(vol.Coerce(float), vol.Range(min=0, max=10000))),
    vol.Optional("unit", default="mg"): vol.All(str, vol.Length(max=12)),
})
SUBSTANCE_SCHEMA = vol.Schema({
    vol.Required("id"): _ID,
    vol.Required("name"): _NAME,
    vol.Optional("profile", default="custom"): _PROFILE,
    vol.Optional("color", default="#d4537e"): _COLOR,
    vol.Optional("half_life_h", default=None): vol.Any(None, vol.All(vol.Coerce(float), vol.Range(min=0.2, max=72))),
    vol.Optional("tmax_h", default=None): vol.Any(None, vol.All(vol.Coerce(float), vol.Range(min=0.1, max=24))),
    vol.Optional("onset_h", default=None): vol.Any(None, vol.All(vol.Coerce(float), vol.Range(min=0, max=24))),
    vol.Optional("effect_h", default=None): vol.Any(None, vol.All(vol.Coerce(float), vol.Range(min=0.25, max=48))),
    vol.Optional("ha_sensor", default=False): bool,
    vol.Optional("items", default=[]): vol.All([ITEM_SCHEMA], vol.Length(max=24)),
})
CONDITION_SCHEMA = vol.Schema({
    vol.Required("substance"): _ID,
    # "hours": had some or no intake from_h–to_h before. "working": within the
    # typical duration of action. "worn_off": up to 12 h after it ended.
    vol.Optional("when", default="hours"): vol.In(["hours", "working", "worn_off"]),
    vol.Required("present"): bool,
    vol.Required("from_h"): _HOURS,
    vol.Required("to_h"): _HOURS,
})
COMPARISON_SCHEMA = vol.Schema({
    vol.Required("id"): _ID,
    vol.Required("name"): _NAME,
    vol.Required("conditions"): vol.All([CONDITION_SCHEMA], vol.Length(max=6)),
})
WINDOW_SCHEMA = vol.Schema({
    vol.Required("weekdays"): vol.All([vol.All(int, vol.Range(min=0, max=6))], vol.Length(min=1)),
    vol.Required("from"): _TIME,
    vol.Required("to"): _TIME,
})
SPORT_ZONE_SCHEMA = vol.Schema({
    vol.Required("id"): _ID,
    vol.Required("zone"): vol.All(str, vol.Match(r"^zone\.[a-z0-9_]+$")),
    vol.Required("person"): vol.All(str, vol.Match(r"^(person|device_tracker)\.[a-z0-9_]+$")),
    vol.Required("activity"): _NAME,
    vol.Optional("min_minutes", default=60): vol.All(vol.Coerce(int), vol.Range(min=1, max=600)),
    # Either time windows, or a Schedule helper, or neither (any time counts).
    vol.Optional("windows", default=[]): vol.All([WINDOW_SCHEMA], vol.Length(max=14)),
    vol.Optional("schedule", default=""): vol.All(str, vol.Match(r"^(schedule\.[a-z0-9_]+)?$")),
})


def _unique_ids(key: str):
    def check(items: list[dict]) -> list[dict]:
        ids = [i["id"] for i in items]
        if len(ids) != len(set(ids)):
            raise vol.Invalid(f"Duplicate id in {key}")
        return items
    return check


SETTINGS_SCHEMA = vol.Schema({
    vol.Required("day_start_hour"): vol.All(vol.Coerce(int), vol.Range(min=0, max=8)),
    vol.Required("axis_start_hour"): vol.All(vol.Coerce(int), vol.Range(min=0, max=12)),
    vol.Required("axis_end_hour"): vol.All(vol.Coerce(int), vol.Range(min=16, max=32)),
    vol.Required("min_samples"): vol.All(vol.Coerce(int), vol.Range(min=1, max=100)),
    vol.Required("negligible_share"): vol.All(vol.Coerce(float), vol.Range(min=0.01, max=0.5)),
    vol.Required("notify_service"): vol.All(str, vol.Match(r"^([a-z0-9_]+)?$")),
    vol.Required("states"): vol.All([STATE_SCHEMA], vol.Length(min=1, max=12), _unique_ids("states")),
    vol.Required("substances"): vol.All([SUBSTANCE_SCHEMA], vol.Length(max=12), _unique_ids("substances")),
    vol.Required("comparisons"): vol.All([COMPARISON_SCHEMA], vol.Length(max=10), _unique_ids("comparisons")),
    vol.Required("sleep_substance"): vol.Any("", _ID),
    vol.Required("sport_zones"): vol.All([SPORT_ZONE_SCHEMA], vol.Length(max=12), _unique_ids("sport_zones")),
})


def migrate(stored: dict[str, Any]) -> dict[str, Any]:
    """Convert settings from before 0.3.0 (a flat "items" list pointing at
    profiles, display settings keyed by profile) to substances with their
    items inside. Substance ids are the old profile ids, so comparison lines,
    sensors and entries keep working. Newer settings come back unchanged."""
    if not ("items" in stored or isinstance(stored.get("substances"), dict)):
        return stored
    s = copy.deepcopy(stored)
    old = s.get("substances") if isinstance(s.get("substances"), dict) else {}
    sensors = set(s.pop("ha_sensors", None) or [])
    by_profile: dict[str, dict[str, Any]] = {}
    for item in s.pop("items", None) or []:
        pid = item.get("profile") if item.get("profile") in PROFILES else "custom"
        if pid not in by_profile:
            o = old.get(pid) or {}
            by_profile[pid] = {
                "id": pid,
                "name": o.get("label") or PROFILES[pid]["name"],
                "profile": pid,
                "color": o.get("color", "#d4537e"),
                "half_life_h": o.get("half_life_h"),
                "tmax_h": o.get("tmax_h"),
                "ha_sensor": pid in sensors,
                "items": [],
            }
        by_profile[pid]["items"].append({k: v for k, v in item.items() if k != "profile"})
    s["substances"] = list(by_profile.values())
    for comp in s.get("comparisons") or []:
        for cond in comp.get("conditions") or []:
            if "profile" in cond:
                cond["substance"] = cond.pop("profile")
    if "sleep_profile" in s:
        s["sleep_substance"] = s.pop("sleep_profile")
    return s


def merge_defaults(stored: dict[str, Any] | None) -> dict[str, Any]:
    merged = copy.deepcopy(DEFAULT_SETTINGS)
    if stored:
        merged.update({k: v for k, v in migrate(stored).items() if k in DEFAULT_SETTINGS})
    return merged


def all_items(settings: dict[str, Any]) -> list[dict[str, Any]]:
    """Every item, with the id of its substance under "substance"."""
    return [{**it, "substance": sub["id"]} for sub in settings.get("substances", []) for it in sub.get("items", [])]


def validate(settings: dict[str, Any]) -> dict[str, Any]:
    result = SETTINGS_SCHEMA(merge_defaults(settings))
    ids = [it["id"] for it in all_items(result)]
    if len(ids) != len(set(ids)):
        raise vol.Invalid("Two things you take have the same id")
    known = {sub["id"] for sub in result["substances"]}
    for comp in result["comparisons"]:
        for cond in comp["conditions"]:
            if cond["substance"] not in known:
                raise vol.Invalid(f"The line \"{comp['name']}\" uses a substance that isn't in your list")
    if result["sleep_substance"] not in known:
        result["sleep_substance"] = result["substances"][0]["id"] if result["substances"] else ""
    return result


def slugify_id(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return slug[:40] or "item"
