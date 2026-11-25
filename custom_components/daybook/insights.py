"""Pattern statistics for the Patterns view.

Plain counting, no machine learning. Every result carries its sample size so
the panel can say "needs more data" instead of showing noise. These are
observations, not causes: you probably drink coffee *because* you feel tired,
which makes coffee look like it goes with tiredness.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .const import (
    KIND_CAFFEINE,
    KIND_MED,
    KIND_SLEEP,
    KIND_STATE,
    MED_SKIPPED,
    MED_TAKEN,
    STATUS_CONFIRMED,
)
from .model import caffeine_at, caffeine_doses

BANDS = ((6, 10), (10, 14), (14, 18), (18, 22), (22, 30))
BAND_LABELS = ("6–10", "10–14", "14–18", "18–22", "22+")
DOSE_BINS = (0, 1, 2, 3, 4, 6, 8, 12)


def _confirmed(entries: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    return [
        e for e in entries
        if e["kind"] == kind and e["status"] == STATUS_CONFIRMED and not e.get("deleted")
    ]


def day_key(ts: float, tz: ZoneInfo, day_start_hour: int) -> str:
    """The journal day a timestamp belongs to (after midnight counts as yesterday)."""
    local = datetime.fromtimestamp(ts, tz) - timedelta(hours=day_start_hour)
    return local.date().isoformat()


def _local_hour(ts: float, tz: ZoneInfo, day_start_hour: int) -> float:
    """Hour of the journal day, so 01:30 after a late night reads as 25.5."""
    local = datetime.fromtimestamp(ts, tz)
    hour = local.hour + local.minute / 60
    return hour + 24 if hour < day_start_hour else hour


def _band(hour: float) -> int | None:
    for i, (lo, hi) in enumerate(BANDS):
        if lo <= hour < hi:
            return i
    return None


def compute(entries: list[dict[str, Any]], settings: dict[str, Any], tz: ZoneInfo) -> dict[str, Any]:
    dsh = int(settings.get("day_start_hour", 4))
    half_life = float(settings.get("caffeine_half_life_h", 5.0))
    absorb = float(settings.get("caffeine_absorption_min", 45))
    state_defs = settings.get("states", [])
    high = {s["id"] for s in state_defs if s.get("energy") == "high"}

    states = _confirmed(entries, KIND_STATE)
    caffeine = _confirmed(entries, KIND_CAFFEINE)
    meds = _confirmed(entries, KIND_MED)
    sleeps = _confirmed(entries, KIND_SLEEP)
    doses = caffeine_doses(caffeine)

    # Per journal day: first dose time per med and taken/skipped status.
    med_days: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for m in meds:
        day = day_key(m["start"], tz, dsh)
        status = (m.get("value") or {}).get("status", MED_TAKEN)
        rec = med_days[m["item"]].setdefault(day, {"status": status, "first": None})
        if status == MED_TAKEN:
            rec["status"] = MED_TAKEN
            if rec["first"] is None or m["start"] < rec["first"]:
                rec["first"] = m["start"]

    any_med_taken_days = {
        day for days in med_days.values() for day, r in days.items() if r["status"] == MED_TAKEN
    }
    all_days = {day_key(e["start"], tz, dsh) for e in entries if not e.get("deleted")}

    # 1. Weekday x time-of-day grid.
    grid = [[Counter() for _ in BANDS] for _ in range(7)]
    for s in states:
        local = datetime.fromtimestamp(s["start"], tz)
        hour = _local_hour(s["start"], tz, dsh)
        wd = (local - timedelta(hours=dsh)).weekday()
        band = _band(hour)
        if band is not None:
            grid[wd][band][s["item"]] += 1
    weekday_grid = [[dict(c) for c in row] for row in grid]

    # 2. State mix by context: caffeine 1-4 h before, med taken earlier that day.
    def caffeine_window(ts: float) -> bool:
        return any(ts - 4 * 3600 <= t <= ts - 3600 for t, _ in doses)

    def recent_caffeine(ts: float) -> bool:
        return any(ts - 4 * 3600 <= t <= ts for t, _ in doses)

    def med_before(ts: float) -> bool:
        day = day_key(ts, tz, dsh)
        for days in med_days.values():
            rec = days.get(day)
            if rec and rec["status"] == MED_TAKEN and rec["first"] and rec["first"] <= ts:
                return True
        return False

    contexts = {
        "med_and_coffee": Counter(),
        "med_only": Counter(),
        "coffee_only": Counter(),
        "neither": Counter(),
    }
    for s in states:
        ts = s["start"]
        med = med_before(ts)
        if caffeine_window(ts):
            key = "med_and_coffee" if med else "coffee_only"
        elif recent_caffeine(ts):
            continue  # Coffee under an hour ago: still kicking in, leave it out.
        else:
            key = "med_only" if med else "neither"
        contexts[key][s["item"]] += 1

    # 3. Hours since dose, per med, on days it was taken.
    since_dose: dict[str, list[dict[str, int]]] = {}
    for med_id, days in med_days.items():
        bins = [Counter() for _ in DOSE_BINS]
        for s in states:
            rec = days.get(day_key(s["start"], tz, dsh))
            if not rec or rec["status"] != MED_TAKEN or not rec["first"]:
                continue
            h = (s["start"] - rec["first"]) / 3600
            if h < 0:
                continue
            idx = max(i for i, lo in enumerate(DOSE_BINS) if h >= lo)
            bins[idx][s["item"]] += 1
        since_dose[med_id] = [dict(b) for b in bins]

    # 4. Taken vs skipped days, per med.
    taken_vs_skipped: dict[str, dict[str, Any]] = {}
    for med_id, days in med_days.items():
        groups = {MED_TAKEN: Counter(), MED_SKIPPED: Counter()}
        day_counts = Counter(r["status"] for r in days.values())
        for s in states:
            rec = days.get(day_key(s["start"], tz, dsh))
            if rec:
                groups[rec["status"]][s["item"]] += 1
        taken_vs_skipped[med_id] = {
            "taken": dict(groups[MED_TAKEN]),
            "skipped": dict(groups[MED_SKIPPED]),
            "days_taken": day_counts[MED_TAKEN],
            "days_skipped": day_counts[MED_SKIPPED],
        }
    unrecorded_days = sorted(all_days - {d for days in med_days.values() for d in days})

    # 5. Share of high-energy states by hour of the journal day.
    by_hour: dict[int, list[int]] = defaultdict(lambda: [0, 0])
    for s in states:
        hour = int(_local_hour(s["start"], tz, dsh))
        by_hour[hour][1] += 1
        if s["item"] in high:
            by_hour[hour][0] += 1
    energy_by_hour = [
        {"hour": h, "high": v[0], "n": v[1]} for h, v in sorted(by_hour.items())
    ]

    # 6. Caffeine left at sleep start vs sleep duration.
    sleep_pairs = []
    for sl in sleeps:
        if not sl.get("end"):
            continue
        sleep_pairs.append({
            "day": day_key(sl["start"], tz, dsh),
            "caffeine_mg": round(caffeine_at(doses, sl["start"], half_life, absorb), 1),
            "duration_h": round((sl["end"] - sl["start"]) / 3600, 2),
        })

    # 7. Daily totals for the trend line.
    daily: dict[str, dict[str, Any]] = defaultdict(lambda: {"caffeine_mg": 0.0, "states": Counter()})
    for t, mg in doses:
        daily[day_key(t, tz, dsh)]["caffeine_mg"] += mg
    for s in states:
        daily[day_key(s["start"], tz, dsh)]["states"][s["item"]] += 1
    daily_list = [
        {
            "day": d,
            "caffeine_mg": round(v["caffeine_mg"]),
            "states": dict(v["states"]),
            "med_taken": d in any_med_taken_days,
        }
        for d, v in sorted(daily.items())
    ]

    return {
        "n_states": len(states),
        "n_days": len(all_days),
        "band_labels": list(BAND_LABELS),
        "weekday_grid": weekday_grid,
        "contexts": {k: dict(v) for k, v in contexts.items()},
        "dose_bins": list(DOSE_BINS),
        "since_dose": since_dose,
        "taken_vs_skipped": taken_vs_skipped,
        "unrecorded_med_days": unrecorded_days,
        "energy_by_hour": energy_by_hour,
        "sleep_vs_caffeine": sleep_pairs,
        "daily": daily_list,
    }
