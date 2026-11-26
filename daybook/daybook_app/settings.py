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
    vol.Required("profile"): _PROFILE,
    vol.Optional("amount", default=None): vol.Any(None, vol.All(vol.Coerce(float), vol.Range(min=0, max=10000))),
    vol.Optional("unit", default="mg"): vol.All(str, vol.Length(max=12)),
})
SUBSTANCE_SCHEMA = vol.Schema({
    vol.Optional("color", default="#d4537e"): _COLOR,
    vol.Optional("label", default=""): vol.All(str, vol.Length(max=60)),
    vol.Optional("half_life_h", default=None): vol.Any(None, vol.All(vol.Coerce(float), vol.Range(min=0.2, max=72))),
    vol.Optional("tmax_h", default=None): vol.Any(None, vol.All(vol.Coerce(float), vol.Range(min=0.1, max=24))),
})
CONDITION_SCHEMA = vol.Schema({
    vol.Required("profile"): _PROFILE,
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
    vol.Required("ha_sensors"): [_PROFILE],
    vol.Required("states"): vol.All([STATE_SCHEMA], vol.Length(min=1, max=12), _unique_ids("states")),
    vol.Required("items"): vol.All([ITEM_SCHEMA], vol.Length(max=24), _unique_ids("items")),
    vol.Required("substances"): {_PROFILE: SUBSTANCE_SCHEMA},
    vol.Required("comparisons"): vol.All([COMPARISON_SCHEMA], vol.Length(max=10), _unique_ids("comparisons")),
    vol.Required("sleep_profile"): _PROFILE,
    vol.Required("sport_zones"): vol.All([SPORT_ZONE_SCHEMA], vol.Length(max=12), _unique_ids("sport_zones")),
})


def merge_defaults(stored: dict[str, Any] | None) -> dict[str, Any]:
    merged = copy.deepcopy(DEFAULT_SETTINGS)
    if stored:
        merged.update({k: v for k, v in stored.items() if k in DEFAULT_SETTINGS})
    return merged


def validate(settings: dict[str, Any]) -> dict[str, Any]:
    result = SETTINGS_SCHEMA(merge_defaults(settings))
    # Every substance used by an item gets display settings.
    for item in result["items"]:
        result["substances"].setdefault(item["profile"], SUBSTANCE_SCHEMA({}))
    return result


def slugify_id(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return slug[:40] or "item"
