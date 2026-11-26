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
    # Substances whose level is published to Home Assistant as a sensor.
    "ha_sensors": ["caffeine"],
    "states": [
        {"id": "productive", "name": "Productive", "color": "#1baf7a", "energy": ENERGY_HIGH},
        {"id": "creative", "name": "Creative", "color": "#6250d6", "energy": ENERGY_HIGH},
        {"id": "overstimulated", "name": "Overstimulated", "color": "#eb6834", "energy": ENERGY_HIGH},
        {"id": "tired", "name": "Tired", "color": "#2a78d6", "energy": ENERGY_LOW},
        {"id": "lazy", "name": "Lazy", "color": "#9a9890", "energy": ENERGY_LOW},
    ],
    # Things you take. Each points to a substance profile in substances.py.
    "items": [
        {"id": "coffee", "name": "Coffee", "profile": "caffeine", "amount": 90, "unit": "mg"},
        {"id": "espresso", "name": "Espresso", "profile": "caffeine", "amount": 65, "unit": "mg"},
        {"id": "black_tea", "name": "Black tea", "profile": "caffeine", "amount": 45, "unit": "mg"},
    ],
    # Per-substance colour and optional overrides of the published averages.
    "substances": {
        "caffeine": {"color": "#eda100", "half_life_h": None, "tmax_h": None},
    },
    # Lines of the "How you felt, depending on what you'd had" chart.
    "comparisons": [
        {"id": "after_caffeine", "name": "1–4 h after caffeine",
         "conditions": [{"profile": "caffeine", "present": True, "from_h": 1, "to_h": 4}]},
        {"id": "no_caffeine", "name": "No caffeine in the last 4 h",
         "conditions": [{"profile": "caffeine", "present": False, "from_h": 0, "to_h": 4}]},
    ],
    "sleep_profile": "caffeine",
    "sport_zones": [],
}
