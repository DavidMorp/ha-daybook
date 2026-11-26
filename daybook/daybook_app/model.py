"""How much of each substance is in the body, from your intake entries."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .const import KIND_INTAKE, STATUS_CONFIRMED
from .substances import PROFILES, amount_fraction, single_dose_peak


def profile_params(settings: dict[str, Any], profile_id: str) -> tuple[dict, float | None, float | None]:
    profile = PROFILES.get(profile_id, PROFILES["custom"])
    overrides = settings.get("substances", {}).get(profile_id) or {}
    return profile, overrides.get("half_life_h") or None, overrides.get("tmax_h") or None


def reference_amount(settings: dict[str, Any], profile_id: str) -> float:
    """The usual dose: the amount of the first item using this substance."""
    for item in settings.get("items", []):
        if item["profile"] == profile_id and item.get("amount"):
            return float(item["amount"])
    return 1.0


def profiles_in_use(settings: dict[str, Any]) -> list[str]:
    seen: list[str] = []
    for item in settings.get("items", []):
        if item["profile"] not in seen:
            seen.append(item["profile"])
    return seen


def doses(entries: Iterable[dict[str, Any]], settings: dict[str, Any], profile_id: str) -> list[tuple[float, float]]:
    """(timestamp, amount) of confirmed intakes of one substance."""
    items = {i["id"]: i for i in settings.get("items", [])}
    out = []
    for e in entries:
        if e.get("kind") != KIND_INTAKE or e.get("status") != STATUS_CONFIRMED or e.get("deleted"):
            continue
        item = items.get(e.get("item"))
        if item is None or item["profile"] != profile_id:
            continue
        amount = (e.get("value") or {}).get("amount")
        if not isinstance(amount, (int, float)):
            amount = item.get("amount") or 1.0
        out.append((float(e["start"]), float(amount)))
    return out


def amount_at(dose_list: Iterable[tuple[float, float]], ts: float, settings: dict[str, Any], profile_id: str) -> float:
    """Estimated amount in the body, in the item's unit (mg for caffeine)."""
    profile, hl, tm = profile_params(settings, profile_id)
    return sum(a * amount_fraction((ts - t0) / 3600, profile, hl, tm) for t0, a in dose_list)


def level_at(dose_list: Iterable[tuple[float, float]], ts: float, settings: dict[str, Any], profile_id: str) -> float:
    """Relative level: 1.0 is the peak of one usual dose."""
    profile, hl, tm = profile_params(settings, profile_id)
    peak = single_dose_peak(profile, hl, tm) * reference_amount(settings, profile_id)
    if peak <= 0:
        return 0.0
    return amount_at(dose_list, ts, settings, profile_id) / peak
