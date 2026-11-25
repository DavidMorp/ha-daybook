"""Tests for the parts that don't need a running Home Assistant."""

import math
from zoneinfo import ZoneInfo

import pytest

from custom_components.daybook import insights
from custom_components.daybook.model import caffeine_at, med_level
from custom_components.daybook.settings import validate
from custom_components.daybook.store import DaybookStore, StoreError
from custom_components.daybook.substances import PROFILES, amount_fraction, ka_from_tmax, single_dose_peak

TZ = ZoneInfo("Europe/Amsterdam")
H = 3600


@pytest.fixture
def store(tmp_path):
    s = DaybookStore(str(tmp_path / "d.db"))
    s.open()
    yield s
    s.close()


def test_add_edit_delete_restore_keeps_history(store):
    e = store.add({"kind": "state", "item": "tired", "start": 1000.0}, now=1000)
    assert e["status"] == "confirmed" and e["value"] == {}
    e = store.update(e["id"], {"item": "lazy", "start": 900.0}, now=1100)
    assert e["item"] == "lazy" and e["start"] == 900.0
    store.delete(e["id"], now=1200)
    assert store.list() == []
    assert len(store.list(include_deleted=True)) == 1
    store.restore(e["id"], now=1300)
    assert [x["id"] for x in store.list()] == [e["id"]]
    actions = [h["action"] for h in store.history(e["id"])]
    assert actions == ["create", "update", "delete", "restore"]
    assert store.history(e["id"])[1]["before"]["item"] == "tired"


def test_list_overlap_and_validation(store):
    store.add({"kind": "sleep", "start": 0.0, "end": 8 * H})
    store.add({"kind": "note", "start": 10 * H})
    assert len(store.list(4 * H, 9 * H)) == 1  # sleep overlaps the window
    assert len(store.list(9 * H, 11 * H)) == 1
    with pytest.raises(StoreError):
        store.add({"kind": "nope", "start": 0.0})
    with pytest.raises(StoreError):
        store.add({"kind": "sleep", "start": 10.0, "end": 5.0})


def test_last_by_source(store):
    store.add({"kind": "note", "start": 1.0, "source": "box"}, now=100)
    store.add({"kind": "note", "start": 2.0, "source": "panel"}, now=200)
    assert store.last_by_source("box", since=0)["source"] == "box"
    assert store.last_by_source(None, since=0)["source"] == "panel"
    assert store.last_by_source("box", since=150) is None


@pytest.mark.parametrize("pid", [p for p in PROFILES])
def test_profiles_peak_near_tmax(pid):
    p = PROFILES[pid]
    if len(p["components"]) > 1:
        return  # multi-release products peak elsewhere by design
    ka = ka_from_tmax(p["tmax_h"], p["half_life_h"])
    ke = math.log(2) / p["half_life_h"]
    assert math.isclose(math.log(ka / ke) / (ka - ke), p["tmax_h"], rel_tol=1e-3)
    peak_t = max(range(1, 2000), key=lambda i: amount_fraction(i / 100, p)) / 100
    assert abs(peak_t - p["tmax_h"]) < 0.05


def test_oros_peaks_late_and_bimodal_has_two_peaks():
    oros = PROFILES["mph_oros"]
    peak_t = max(range(1, 2400), key=lambda i: amount_fraction(i / 100, oros)) / 100
    assert 5 <= peak_t <= 10
    bi = PROFILES["mph_er_bimodal"]
    ys = [amount_fraction(i / 10, bi) for i in range(0, 160)]
    peaks = [i for i in range(1, len(ys) - 1) if ys[i - 1] < ys[i] > ys[i + 1]]
    assert len(peaks) == 2


def test_caffeine_decays_by_half_life():
    doses = [(0.0, 100.0)]
    # Long after absorption, five hours halves the amount.
    a, b = caffeine_at(doses, 6 * H), caffeine_at(doses, 11 * H)
    assert math.isclose(b / a, 0.5, rel_tol=0.02)
    assert caffeine_at(doses, -1) == 0


def test_med_level_is_relative_to_usual_dose():
    med = {"id": "x", "profile": "lisdexamfetamine", "dose": 30}
    peak = max(med_level([(0.0, 30.0)], t * 600, med) for t in range(1, 200))
    assert math.isclose(peak, 1.0, rel_tol=0.01)
    assert single_dose_peak(PROFILES["lisdexamfetamine"]) > 0


def test_settings_validation():
    s = validate({"meds": [{"id": "elv", "name": "Elvanse", "dose": 30, "profile": "lisdexamfetamine"}]})
    assert s["meds"][0]["unit"] == "mg" and s["drinks"]
    with pytest.raises(Exception):
        validate({"meds": [{"id": "a", "name": "A"}, {"id": "a", "name": "B"}]})


def _ts(day, hour):
    from datetime import datetime
    return datetime(2026, 11, day, int(hour), int((hour % 1) * 60), tzinfo=TZ).timestamp()


def test_insights_contexts_and_med_days():
    settings = validate({"meds": [{"id": "elv", "name": "Elvanse", "dose": 30, "profile": "lisdexamfetamine"}]})
    def e(kind, item, t, **value):
        return {"kind": kind, "item": item, "start": t, "end": None, "value": value,
                "status": "confirmed", "deleted": None}
    entries = [
        e("med", "elv", _ts(16, 8), status="taken", dose=30),
        e("caffeine", "coffee", _ts(16, 9), mg=90),
        e("state", "overstimulated", _ts(16, 11)),   # med + coffee 2 h before
        e("state", "productive", _ts(16, 15)),       # med, coffee 6 h ago -> med only
        e("med", "elv", _ts(17, 8), status="skipped"),
        e("state", "tired", _ts(17, 10)),            # skipped day, no coffee
        e("caffeine", "coffee", _ts(17, 12), mg=90),
        e("state", "lazy", _ts(17, 12.5)),           # coffee 30 min ago: excluded
        e("state", "creative", _ts(18, 1)),          # 01:00 belongs to the 17th
    ]
    r = insights.compute(entries, settings, TZ)
    assert r["contexts"]["med_and_coffee"] == {"overstimulated": 1}
    assert r["contexts"]["med_only"] == {"productive": 1}
    assert r["contexts"]["neither"] == {"tired": 1, "creative": 1}
    tvs = r["taken_vs_skipped"]["elv"]
    assert tvs["days_taken"] == 1 and tvs["days_skipped"] == 1
    assert tvs["skipped"] == {"tired": 1, "lazy": 1, "creative": 1}
    assert r["unrecorded_med_days"] == []
    assert r["n_days"] == 2
