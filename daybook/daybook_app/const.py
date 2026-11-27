"""Constants for Daybook."""

from __future__ import annotations

from typing import Final

KIND_STATE: Final = "state"
KIND_INTAKE: Final = "intake"
KIND_SPORT: Final = "sport"
KIND_SLEEP: Final = "sleep"
KIND_NOTE: Final = "note"
KINDS: Final = (KIND_STATE, KIND_INTAKE, KIND_SPORT, KIND_SLEEP, KIND_NOTE)

STATUS_CONFIRMED: Final = "confirmed"
STATUS_DRAFT: Final = "draft"
STATUS_REJECTED: Final = "rejected"
STATUSES: Final = (STATUS_CONFIRMED, STATUS_DRAFT, STATUS_REJECTED)

ENERGY_HIGH: Final = "high"
ENERGY_LOW: Final = "low"
ENERGY_NEUTRAL: Final = "neutral"

NOTIFY_ACTION_PREFIX: Final = "DAYBOOK_"
EVENT_LOGGED: Final = "daybook_logged"

DEFAULT_SETTINGS: Final[dict] = {
    "day_start_hour": 4,
    "axis_start_hour": 6,
    "axis_end_hour": 26,
    "min_samples": 8,
    # Below this share of one usual dose's peak, a substance counts as gone
    # in the charts. Elimination never quite reaches zero.
    "negligible_share": 0.1,
    "notify_service": "",
    "states": [
        {"id": "productive", "name": "Productive", "color": "#1baf7a", "energy": ENERGY_HIGH},
        {"id": "creative", "name": "Creative", "color": "#6250d6", "energy": ENERGY_HIGH},
        {"id": "overstimulated", "name": "Overstimulated", "color": "#eb6834", "energy": ENERGY_HIGH},
        {"id": "tired", "name": "Tired", "color": "#2a78d6", "energy": ENERGY_LOW},
        {"id": "lazy", "name": "Lazy", "color": "#9a9890", "energy": ENERGY_LOW},
    ],
    # What you take, grouped by substance. Each substance starts from a
    # profile in substances.py; half-life and time to peak can be overridden.
    # Item ids are unique across all substances (buttons and entries use them).
    "substances": [
        {"id": "caffeine", "name": "Caffeine", "profile": "caffeine", "color": "#eda100",
         "half_life_h": None, "tmax_h": None, "ha_sensor": True,
         "items": [
             {"id": "coffee", "name": "Coffee", "amount": 90, "unit": "mg"},
             {"id": "espresso", "name": "Espresso", "amount": 65, "unit": "mg"},
             {"id": "black_tea", "name": "Black tea", "amount": 45, "unit": "mg"},
         ]},
    ],
    # Lines of the "How you felt, depending on what you'd had" chart.
    "comparisons": [
        {"id": "after_caffeine", "name": "1–4 h after caffeine",
         "conditions": [{"substance": "caffeine", "present": True, "from_h": 1, "to_h": 4}]},
        {"id": "no_caffeine", "name": "No caffeine in the last 4 h",
         "conditions": [{"substance": "caffeine", "present": False, "from_h": 0, "to_h": 4}]},
    ],
    "sleep_substance": "caffeine",
    "sport_zones": [],
}
