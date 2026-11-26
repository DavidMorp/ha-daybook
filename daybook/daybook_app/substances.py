"""Reference profiles for how long common substances stay in the body.

Caffeine and medication are treated the same way: each is a substance with a
release pattern, a time to peak and a half-life.

Each profile is a one-compartment oral model (the Bateman function) with an
absorption rate derived from the time to peak and an elimination rate from
the half-life. Extended-release products are modelled as several release
components: an immediate part, delayed beads, or a slow, steady release.

These are population averages from published labels and reviews. They show
roughly how much is in your blood, not how strong the effect is. Effects of
stimulants usually end well before the curve reaches zero, and individual
half-lives vary a lot. Not medical advice.
"""

from __future__ import annotations

import math
from typing import Any

# Each component: fraction of the dose, lag before release starts (h), and
# release duration (h, 0 = all at once).
PROFILES: dict[str, dict[str, Any]] = {
    "caffeine": {
        "name": "Caffeine",
        "examples": "Coffee, tea, energy drinks",
        "tmax_h": 0.75,
        "half_life_h": 5.0,
        "half_life_range_h": [1.5, 9.5],
        "components": [{"fraction": 1.0, "lag_h": 0, "release_h": 0}],
        "notes": "Half-life is often 1.5–2× longer with oral contraceptives and shorter in smokers.",
        "verified": True,
        "sources": [
            "https://frontiersin.org/articles/10.3389/fphar.2021.752826/full",
            "https://pubmed.ncbi.nlm.nih.gov/4029248/",
        ],
    },
    "mph_ir": {
        "name": "Methylphenidate, immediate release",
        "examples": "Ritalin, Medikinet (non-retard)",
        "tmax_h": 1.75,
        "half_life_h": 3.0,
        "half_life_range_h": [2.0, 4.0],
        "components": [{"fraction": 1.0, "lag_h": 0, "release_h": 0}],
        "notes": "Effect typically lasts about 3–4 h.",
        "verified": True,
        "sources": ["https://pubmed.ncbi.nlm.nih.gov/15015904/"],
    },
    "mph_er_bimodal": {
        "name": "Methylphenidate 50:50 extended release",
        "examples": "Ritalin LA, Medikinet retard",
        "tmax_h": 1.75,
        "half_life_h": 3.0,
        "half_life_range_h": [2.0, 4.0],
        "components": [
            {"fraction": 0.5, "lag_h": 0, "release_h": 0},
            {"fraction": 0.5, "lag_h": 4.0, "release_h": 0},
        ],
        "notes": "Half the dose is released at once and half later, giving two peaks. "
                 "The ~4 h gap is an estimate; Medikinet retard is taken with food.",
        "verified": False,
        "sources": [
            "https://www.novartis.com/us-en/sites/novartis_us/files/ritalin_la.pdf",
            "https://www.geneesmiddeleninformatiebank.nl/pars/h112772.pdf",
        ],
    },
    "mph_oros": {
        "name": "Methylphenidate OROS",
        "examples": "Concerta and generics",
        "tmax_h": 1.75,
        "half_life_h": 3.5,
        "half_life_range_h": [3.0, 4.0],
        "components": [
            {"fraction": 0.22, "lag_h": 0, "release_h": 0},
            {"fraction": 0.78, "lag_h": 1.0, "release_h": 7.0},
        ],
        "notes": "22% is released at once, the rest steadily over the day. Peak at about 6–10 h.",
        "verified": True,
        "sources": [
            "https://www.thecarlatreport.com/ext/resources/factsheets/MFB7e/METHYLPHENIDATE-ER-(Concerta-Ritalin-SR-and-LA-others)-Fact-Sheet-[G].pdf",
            "https://www.accessdata.fda.gov/drugsatfda_docs/label/2026/021121s34s40s45lbl.pdf",
        ],
    },
    "lisdexamfetamine": {
        "name": "Lisdexamfetamine",
        "examples": "Elvanse, Vyvanse",
        "tmax_h": 4.0,
        "half_life_h": 10.0,
        "half_life_range_h": [9.0, 12.0],
        "components": [{"fraction": 1.0, "lag_h": 0, "release_h": 0}],
        "notes": "A prodrug converted to d-amphetamine; the curve is d-amphetamine. "
                 "Peak about 3.8 h fasted, 4.7 h with food. Effect up to ~14 h in adults.",
        "verified": True,
        "sources": [
            "https://pubmed.ncbi.nlm.nih.gov/27021968/",
            "https://pubmed.ncbi.nlm.nih.gov/20173084/",
        ],
    },
    "dexamfetamine_ir": {
        "name": "Dexamfetamine, immediate release",
        "examples": "Attentin",
        "tmax_h": 3.0,
        "half_life_h": 9.0,
        "half_life_range_h": [7.0, 12.0],
        "components": [{"fraction": 1.0, "lag_h": 0, "release_h": 0}],
        "notes": "The effect usually ends after about 4–6 h, long before it leaves the blood.",
        "verified": True,
        "sources": ["https://pmc.ncbi.nlm.nih.gov/articles/PMC5594082/table/T1"],
    },
    "amphetamine_xr": {
        "name": "Mixed amphetamine salts, extended release",
        "examples": "Adderall XR",
        "tmax_h": 3.0,
        "half_life_h": 10.0,
        "half_life_range_h": [9.0, 13.0],
        "components": [
            {"fraction": 0.5, "lag_h": 0, "release_h": 0},
            {"fraction": 0.5, "lag_h": 4.0, "release_h": 0},
        ],
        "notes": "Two bead types; label time to peak is about 7 h (later with food).",
        "verified": True,
        "sources": [
            "https://webarchive.library.unt.edu/eot2008/20090118031732/http:/www.fda.gov/medwatch/safety/2006/Jul_PIs/AdderallXR_PI.pdf",
        ],
    },
    "guanfacine_er": {
        "name": "Guanfacine, extended release",
        "examples": "Intuniv",
        "tmax_h": 5.0,
        "half_life_h": 17.0,
        "half_life_range_h": [10.0, 30.0],
        "components": [{"fraction": 1.0, "lag_h": 0, "release_h": 0}],
        "notes": "Not a stimulant. With daily doses it builds up to a steady level over several days.",
        "verified": True,
        "sources": ["https://pmc.ncbi.nlm.nih.gov/articles/PMC2935643"],
    },
    "atomoxetine": {
        "name": "Atomoxetine",
        "examples": "Strattera",
        "tmax_h": 1.5,
        "half_life_h": 5.0,
        "half_life_range_h": [3.0, 24.0],
        "components": [{"fraction": 1.0, "lag_h": 0, "release_h": 0}],
        "notes": "Not a stimulant; its effect builds over weeks, not hours. Much longer "
                 "half-life in slow (CYP2D6 poor) metabolisers. Numbers not verified.",
        "verified": False,
        "sources": [],
    },
    "custom": {
        "name": "Custom",
        "examples": "Set your own time to peak and half-life",
        "tmax_h": 1.5,
        "half_life_h": 4.0,
        "half_life_range_h": None,
        "components": [{"fraction": 1.0, "lag_h": 0, "release_h": 0}],
        "notes": "",
        "verified": False,
        "sources": [],
    },
}

DISCLAIMER = (
    "Estimates from published averages of how much is in your blood, not how strong "
    "the effect is. Your body may differ a lot. Not medical advice: talk to your "
    "prescriber before changing how you take anything."
)


def ka_from_tmax(tmax_h: float, half_life_h: float) -> float:
    """Absorption rate (1/h) giving a single-dose peak at tmax_h."""
    ke = math.log(2) / half_life_h
    # tmax = ln(ka/ke) / (ka - ke) is decreasing in ka for ka > ke; bisect.
    if tmax_h >= 1 / ke:  # Peak can't be later than 1/ke for ka > ke.
        return ke * 1.0001
    lo, hi = ke * 1.0001, 200.0
    for _ in range(100):
        mid = (lo + hi) / 2
        t = math.log(mid / ke) / (mid - ke)
        if t > tmax_h:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def _bateman(dt_h: float, ka: float, ke: float) -> float:
    if dt_h <= 0:
        return 0.0
    return ka / (ka - ke) * (math.exp(-ke * dt_h) - math.exp(-ka * dt_h))


def amount_fraction(dt_h: float, profile: dict[str, Any], half_life_h: float | None = None,
                    tmax_h: float | None = None) -> float:
    """Fraction of one dose in the body dt_h hours after taking it."""
    hl = half_life_h or profile["half_life_h"]
    tm = tmax_h or profile["tmax_h"]
    ke = math.log(2) / hl
    ka = ka_from_tmax(tm, hl)
    total = 0.0
    for comp in profile["components"]:
        t = dt_h - comp["lag_h"]
        if t <= 0:
            continue
        if comp["release_h"] <= 0:
            total += comp["fraction"] * _bateman(t, ka, ke)
        else:
            steps = 24
            width = comp["release_h"] / steps
            for i in range(steps):
                total += comp["fraction"] / steps * _bateman(t - (i + 0.5) * width, ka, ke)
    return total


def single_dose_peak(profile: dict[str, Any], half_life_h: float | None = None,
                     tmax_h: float | None = None) -> float:
    return max(amount_fraction(i / 20, profile, half_life_h, tmax_h) for i in range(1, 20 * 36))


def hours_until_below(profile: dict[str, Any], share: float, half_life_h: float | None = None,
                      tmax_h: float | None = None) -> float | None:
    """Hours after one dose until it falls below `share` of its peak, after peaking."""
    peak = single_dose_peak(profile, half_life_h, tmax_h)
    peaked = False
    for i in range(1, 20 * 96):
        v = amount_fraction(i / 20, profile, half_life_h, tmax_h) / peak
        if v > 0.99:
            peaked = True
        if peaked and v < share:
            return i / 20
    return None
