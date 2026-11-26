"""Pattern statistics for the Patterns view.

Plain counting, no machine learning. Every result carries its sample size so
the panel can say "needs more data" instead of showing noise. These are
observations, not causes: you probably drink coffee *because* you feel tired,
which makes coffee look like it goes with tiredness.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, tzinfo
from typing import Any

from .const import KIND_INTAKE, KIND_SLEEP, KIND_STATE, STATUS_CONFIRMED
from .model import doses, level_at, profiles_in_use

BANDS = ((6, 10), (10, 14), (14, 18), (18, 22), (22, 30))
BAND_LABELS = ("6–10", "10–14", "14–18", "18–22", "22+")
SINCE_BINS = (0, 1, 2, 3, 4, 6, 8, 12)


def _confirmed(entries: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    return [
        e for e in entries
        if e["kind"] == kind and e["status"] == STATUS_CONFIRMED and not e.get("deleted")
    ]


def day_key(ts: float, tz: tzinfo, day_start_hour: int) -> str:
    """The journal day a timestamp belongs to (after midnight counts as yesterday)."""
    local = datetime.fromtimestamp(ts, tz) - timedelta(hours=day_start_hour)
    return local.date().isoformat()


def _local_hour(ts: float, tz: tzinfo, day_start_hour: int) -> float:
    """Hour of the journal day, so 01:30 after a late night reads as 25.5."""
    local = datetime.fromtimestamp(ts, tz)
    hour = local.hour + local.minute / 60
    return hour + 24 if hour < day_start_hour else hour


def _band(hour: float) -> int | None:
    for i, (lo, hi) in enumerate(BANDS):
        if lo <= hour < hi:
            return i
    return None


def matches(conditions: list[dict[str, Any]], ts: float, intake_times: dict[str, list[float]]) -> bool:
    """True when every condition holds for a check-in at ts."""
    for c in conditions:
        lo, hi = ts - c["to_h"] * 3600, ts - c["from_h"] * 3600
        found = any(lo <= t <= hi for t in intake_times.get(c["profile"], []))
        if found != c["present"]:
            return False
    return True


def compute(entries: list[dict[str, Any]], settings: dict[str, Any], tz: tzinfo) -> dict[str, Any]:
    dsh = int(settings.get("day_start_hour", 4))
    high = {s["id"] for s in settings.get("states", []) if s.get("energy") == "high"}
    profiles = profiles_in_use(settings)

    states = _confirmed(entries, KIND_STATE)
    sleeps = _confirmed(entries, KIND_SLEEP)
    intake_times = {p: sorted(t for t, _ in doses(entries, settings, p)) for p in profiles}
    all_days = {day_key(e["start"], tz, dsh) for e in entries if not e.get("deleted")}
    state_days = {day_key(s["start"], tz, dsh) for s in states}

    # 1. Weekday x time-of-day grid.
    grid = [[Counter() for _ in BANDS] for _ in range(7)]
    for s in states:
        local = datetime.fromtimestamp(s["start"], tz) - timedelta(hours=dsh)
        band = _band(_local_hour(s["start"], tz, dsh))
        if band is not None:
            grid[local.weekday()][band][s["item"]] += 1

    # 2. Your own comparison lines.
    comparisons = []
    for comp in settings.get("comparisons", []):
        counts = Counter(
            s["item"] for s in states if matches(comp["conditions"], s["start"], intake_times)
        )
        comparisons.append({"id": comp["id"], "name": comp["name"], "counts": dict(counts)})

    # 3. Hours since the first intake of the day, per substance.
    first_of_day: dict[str, dict[str, float]] = {}
    for p, times in intake_times.items():
        firsts: dict[str, float] = {}
        for t in times:
            firsts.setdefault(day_key(t, tz, dsh), t)
        first_of_day[p] = firsts
    since_first: dict[str, list[dict[str, int]]] = {}
    for p, firsts in first_of_day.items():
        bins = [Counter() for _ in SINCE_BINS]
        for s in states:
            first = firsts.get(day_key(s["start"], tz, dsh))
            if first is None or s["start"] < first:
                continue
            h = (s["start"] - first) / 3600
            idx = max(i for i, lo in enumerate(SINCE_BINS) if h >= lo)
            bins[idx][s["item"]] += 1
        since_first[p] = [dict(b) for b in bins]

    # 4. Days with and without each substance (among days with check-ins).
    with_without: dict[str, dict[str, Any]] = {}
    for p, firsts in first_of_day.items():
        with_days = set(firsts)
        groups = {"with": Counter(), "without": Counter()}
        for s in states:
            groups["with" if day_key(s["start"], tz, dsh) in with_days else "without"][s["item"]] += 1
        with_without[p] = {
            "with": dict(groups["with"]),
            "without": dict(groups["without"]),
            "days_with": len(state_days & with_days),
            "days_without": len(state_days - with_days),
        }

    # 5. Share of high-energy states by hour of the journal day.
    by_hour: dict[int, list[int]] = defaultdict(lambda: [0, 0])
    for s in states:
        hour = int(_local_hour(s["start"], tz, dsh))
        by_hour[hour][1] += 1
        if s["item"] in high:
            by_hour[hour][0] += 1
    energy_by_hour = [{"hour": h, "high": v[0], "n": v[1]} for h, v in sorted(by_hour.items())]

    # 6. Sleep length on nights with less or more of a substance left at
    # bedtime than your usual (the median), so the split adapts to your habits.
    sp = settings.get("sleep_profile", "caffeine")
    sp_doses = doses(entries, settings, sp)
    nights = [
        (level_at(sp_doses, sl["start"], settings, sp), (sl["end"] - sl["start"]) / 3600)
        for sl in sleeps if sl.get("end")
    ]
    sleep_split = None
    if len(nights) >= 2:
        levels = sorted(n[0] for n in nights)
        mid = len(levels) // 2
        median = levels[mid] if len(levels) % 2 else (levels[mid - 1] + levels[mid]) / 2
        less = [h for lvl, h in nights if lvl <= median]
        more = [h for lvl, h in nights if lvl > median]
        avg = lambda xs: round(sum(xs) / len(xs), 2) if xs else None  # noqa: E731
        sleep_split = {
            "median_level": median,
            "less": {"nights": len(less), "avg_hours": avg(less)},
            "more": {"nights": len(more), "avg_hours": avg(more)},
        }

    return {
        "n_states": len(states),
        "n_days": len(all_days),
        "band_labels": list(BAND_LABELS),
        "weekday_grid": [[dict(c) for c in row] for row in grid],
        "comparisons": comparisons,
        "since_bins": list(SINCE_BINS),
        "since_first": since_first,
        "with_without": with_without,
        "energy_by_hour": energy_by_hour,
        "sleep_profile": sp,
        "sleep_split": sleep_split,
        "n_nights": len(nights),
    }
