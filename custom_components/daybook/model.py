"""Body-level estimates for caffeine and meds, built on substances.py."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .const import KIND_CAFFEINE, KIND_MED, MED_TAKEN, STATUS_CONFIRMED
from .substances import PROFILES, amount_fraction, single_dose_peak


def caffeine_doses(entries: Iterable[dict[str, Any]]) -> list[tuple[float, float]]:
    """(timestamp, mg) for confirmed caffeine entries."""
    doses = []
    for e in entries:
        if e.get("kind") != KIND_CAFFEINE or e.get("status") != STATUS_CONFIRMED:
            continue
        if e.get("deleted"):
            continue
        mg = (e.get("value") or {}).get("mg")
        if isinstance(mg, (int, float)) and mg > 0:
            doses.append((float(e["start"]), float(mg)))
    return doses


def caffeine_at(
    doses: Iterable[tuple[float, float]],
    ts: float,
    half_life_h: float = 5.0,
    absorption_min: float = 45.0,
) -> float:
    """Estimated caffeine in the body, in mg, at a timestamp.

    absorption_min is the time to peak after a single drink.
    """
    profile = PROFILES["caffeine"]
    return sum(
        mg * amount_fraction((ts - t0) / 3600, profile, half_life_h, absorption_min / 60)
        for t0, mg in doses
    )


def med_doses(entries: Iterable[dict[str, Any]], med_id: str) -> list[tuple[float, float]]:
    """(timestamp, dose) for taken doses of one med. Missing dose counts as 1."""
    doses = []
    for e in entries:
        if e.get("kind") != KIND_MED or e.get("item") != med_id:
            continue
        if e.get("status") != STATUS_CONFIRMED or e.get("deleted"):
            continue
        value = e.get("value") or {}
        if value.get("status", MED_TAKEN) != MED_TAKEN:
            continue
        dose = value.get("dose")
        doses.append((float(e["start"]), float(dose) if isinstance(dose, (int, float)) else 1.0))
    return doses


def med_level(doses: Iterable[tuple[float, float]], ts: float, med: dict[str, Any]) -> float:
    """Relative level: 1.0 is the peak of one usual dose of this med."""
    profile = PROFILES.get(med.get("profile") or "custom", PROFILES["custom"])
    hl = med.get("half_life_h") or None
    tm = med.get("tmax_h") or None
    usual = med.get("dose") or 1.0
    peak = single_dose_peak(profile, hl, tm) * usual
    if peak <= 0:
        return 0.0
    return sum(d * amount_fraction((ts - t0) / 3600, profile, hl, tm) for t0, d in doses) / peak
