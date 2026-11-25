"""Constants for Daybook."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "daybook"
DB_FILENAME: Final = "daybook.db"

PANEL_URL_PATH: Final = "daybook"
PANEL_COMPONENT: Final = "daybook-panel"
STATIC_URL: Final = "/daybook_static"

EVENT_LOGGED: Final = "daybook_logged"
SIGNAL_CHANGED: Final = "daybook_changed"

KIND_STATE: Final = "state"
KIND_CAFFEINE: Final = "caffeine"
KIND_MED: Final = "med"
KIND_SPORT: Final = "sport"
KIND_SLEEP: Final = "sleep"
KIND_NOTE: Final = "note"
KINDS: Final = (KIND_STATE, KIND_CAFFEINE, KIND_MED, KIND_SPORT, KIND_SLEEP, KIND_NOTE)

STATUS_CONFIRMED: Final = "confirmed"
STATUS_DRAFT: Final = "draft"
STATUS_REJECTED: Final = "rejected"
STATUSES: Final = (STATUS_CONFIRMED, STATUS_DRAFT, STATUS_REJECTED)

# A med entry records whether a dose was taken or deliberately skipped.
# "Not recorded" is the absence of an entry, never a stored value.
MED_TAKEN: Final = "taken"
MED_SKIPPED: Final = "skipped"

ENERGY_HIGH: Final = "high"
ENERGY_LOW: Final = "low"
ENERGY_NEUTRAL: Final = "neutral"

NOTIFY_ACTION_PREFIX: Final = "DAYBOOK_"

DEFAULT_SETTINGS: Final[dict] = {
    "day_start_hour": 4,
    "axis_start_hour": 6,
    "axis_end_hour": 26,
    "caffeine_half_life_h": 5.0,
    "caffeine_absorption_min": 45,
    "caffeine_sensor": True,
    "min_samples": 8,
    "notify_service": "",
    "states": [
        {"id": "productive", "name": "Productive", "color": "#1baf7a", "energy": ENERGY_HIGH},
        {"id": "creative", "name": "Creative", "color": "#6250d6", "energy": ENERGY_HIGH},
        {"id": "overstimulated", "name": "Overstimulated", "color": "#eb6834", "energy": ENERGY_HIGH},
        {"id": "tired", "name": "Tired", "color": "#2a78d6", "energy": ENERGY_LOW},
        {"id": "lazy", "name": "Lazy", "color": "#9a9890", "energy": ENERGY_LOW},
    ],
    "drinks": [
        {"id": "coffee", "name": "Coffee", "mg": 90},
        {"id": "espresso", "name": "Espresso", "mg": 65},
        {"id": "black_tea", "name": "Black tea", "mg": 45},
    ],
    "meds": [],
    "sport_zones": [],
}
