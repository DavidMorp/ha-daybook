"""How much of each substance is in the body, from your intake entries.

Substances are the ones in settings (by their id). Each points to a profile in
substances.py and may override its half-life and time to peak.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .const import KIND_INTAKE, STATUS_CONFIRMED
from .substances import PROFILES, amount_fraction, single_dose_peak


def substance(settings: dict[str, Any], substance_id: str) -> dict[str, Any] | None:
    return next((s for s in settings.get("substances", []) if s["id"] == substance_id), None)


def substance_ids(settings: dict[str, Any]) -> list[str]:
    return [s["id"] for s in settings.get("substances", [])]


def profile_params(settings: dict[str, Any], substance_id: str) -> tuple[dict, float | None, float | None]:
    sub = substance(settings, substance_id) or {}
    profile = PROFILES.get(sub.get("profile", ""), PROFILES["custom"])
    return profile, sub.get("half_life_h") or None, sub.get("tmax_h") or None


def reference_amount(settings: dict[str, Any], substance_id: str) -> float:
    """The usual dose: the amount of the substance's first item."""
    for item in (substance(settings, substance_id) or {}).get("items", []):
        if item.get("amount"):
            return float(item["amount"])
    return 1.0


def unit_of(settings: dict[str, Any], substance_id: str) -> str:
    items = (substance(settings, substance_id) or {}).get("items", [])
    return (items[0].get("unit") if items else "") or "mg"


def doses(entries: Iterable[dict[str, Any]], settings: dict[str, Any], substance_id: str) -> list[tuple[float, float]]:
    """(timestamp, amount) of confirmed intakes of one substance."""
    items = {i["id"]: i for i in (substance(settings, substance_id) or {}).get("items", [])}
    out = []
    for e in entries:
        if e.get("kind") != KIND_INTAKE or e.get("status") != STATUS_CONFIRMED or e.get("deleted"):
            continue
        item = items.get(e.get("item"))
        if item is None:
            continue
        amount = (e.get("value") or {}).get("amount")
        if not isinstance(amount, (int, float)):
            amount = item.get("amount") or 1.0
        out.append((float(e["start"]), float(amount)))
    return out


def amount_at(dose_list: Iterable[tuple[float, float]], ts: float, settings: dict[str, Any], substance_id: str) -> float:
    """Estimated amount in the body, in the item's unit (mg for caffeine)."""
    profile, hl, tm = profile_params(settings, substance_id)
    return sum(a * amount_fraction((ts - t0) / 3600, profile, hl, tm) for t0, a in dose_list)


def level_at(dose_list: Iterable[tuple[float, float]], ts: float, settings: dict[str, Any], substance_id: str) -> float:
    """Relative level: 1.0 is the peak of one usual dose."""
    profile, hl, tm = profile_params(settings, substance_id)
    peak = single_dose_peak(profile, hl, tm) * reference_amount(settings, substance_id)
    if peak <= 0:
        return 0.0
    return amount_at(dose_list, ts, settings, substance_id) / peak


def effect_window(settings: dict[str, Any], substance_id: str) -> tuple[float, float] | None:
    """(start, end) of the typical duration of action, in hours after one dose, or None.

    Your own duration wins over the published one; without either there's
    no window and the curve is drawn as plain "in your body".
    """
    sub = substance(settings, substance_id) or {}
    published = PROFILES.get(sub.get("profile", ""), PROFILES["custom"]).get("effect") or {}
    duration = sub.get("effect_h") or published.get("duration_h")
    if not duration:
        return None
    onset = sub.get("onset_h")
    if onset is None:
        onset = published.get("onset_h", 0.0)
    return float(onset), float(max(duration, onset))


def working_intervals(dose_list: Iterable[tuple[float, float]], window: tuple[float, float] | None) -> list[tuple[float, float]]:
    """Merged (start, end) timestamps within at least one dose's typical duration of action."""
    if not window:
        return []
    out: list[list[float]] = []
    for t0 in sorted(t for t, _ in dose_list):
        a, b = t0 + window[0] * 3600, t0 + window[1] * 3600
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]
