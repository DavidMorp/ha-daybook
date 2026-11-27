"""Store, substance models, settings and statistics."""

import math
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from daybook_app import insights
from daybook_app.model import doses, level_at, amount_at
from daybook_app.settings import validate
from daybook_app.store import DaybookStore, StoreError
from daybook_app.substances import PROFILES, amount_fraction, hours_until_below, ka_from_tmax

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
    store.restore(e["id"], now=1300)
    assert [x["id"] for x in store.list()] == [e["id"]]
    assert [h["action"] for h in store.history(e["id"])] == ["create", "update", "delete", "restore"]
    assert store.history(e["id"])[1]["before"]["item"] == "tired"


def test_list_overlap_and_validation(store):
    store.add({"kind": "sleep", "start": 0.0, "end": 8 * H})
    store.add({"kind": "note", "start": 10 * H})
    assert len(store.list(4 * H, 9 * H)) == 1
    with pytest.raises(StoreError):
        store.add({"kind": "med", "start": 0.0})  # old kind is gone
    with pytest.raises(StoreError):
        store.add({"kind": "sleep", "start": 10.0, "end": 5.0})


def test_last_by_source(store):
    store.add({"kind": "note", "start": 1.0, "source": "box"}, now=100)
    store.add({"kind": "note", "start": 2.0, "source": "panel"}, now=200)
    assert store.last_by_source("box", since=0)["source"] == "box"
    assert store.last_by_source("box", since=150) is None


@pytest.mark.parametrize("pid", list(PROFILES))
def test_single_release_profiles_peak_at_tmax(pid):
    p = PROFILES[pid]
    if len(p["components"]) > 1:
        return
    ka = ka_from_tmax(p["tmax_h"], p["half_life_h"])
    ke = math.log(2) / p["half_life_h"]
    assert math.isclose(math.log(ka / ke) / (ka - ke), p["tmax_h"], rel_tol=1e-3)


def test_extended_release_shapes():
    oros = PROFILES["mph_oros"]
    assert 5 <= max(range(1, 2400), key=lambda i: amount_fraction(i / 100, oros)) / 100 <= 10
    bi = PROFILES["mph_er_bimodal"]
    ys = [amount_fraction(i / 10, bi) for i in range(160)]
    assert len([i for i in range(1, 159) if ys[i - 1] < ys[i] > ys[i + 1]]) == 2


def test_caffeine_is_effectively_gone_well_before_a_day():
    gone = hours_until_below(PROFILES["caffeine"], 0.1)
    assert 15 < gone < 19  # ~3.3 half-lives after the peak
    assert hours_until_below(PROFILES["caffeine"], 0.1, half_life_h=3) < gone


def settings():
    return validate({
        "items": [
            {"id": "coffee", "name": "Coffee", "profile": "caffeine", "amount": 90},
            {"id": "elvanse", "name": "Elvanse", "profile": "lisdexamfetamine", "amount": 30},
        ],
        "comparisons": [
            {"id": "both", "name": "Elvanse and coffee", "conditions": [
                {"profile": "lisdexamfetamine", "present": True, "from_h": 0, "to_h": 12},
                {"profile": "caffeine", "present": True, "from_h": 1, "to_h": 4}]},
            {"id": "none", "name": "Neither", "conditions": [
                {"profile": "lisdexamfetamine", "present": False, "from_h": 0, "to_h": 12},
                {"profile": "caffeine", "present": False, "from_h": 0, "to_h": 4}]},
        ],
    })


def test_settings_from_before_0_3_are_converted():
    old = {
        "items": [
            {"id": "coffee", "name": "Coffee", "profile": "caffeine", "amount": 90, "unit": "mg"},
            {"id": "espresso", "name": "Espresso", "profile": "caffeine", "amount": 65, "unit": "mg"},
            {"id": "elvanse", "name": "Elvanse", "profile": "lisdexamfetamine", "amount": 30, "unit": "mg"},
        ],
        "substances": {
            "caffeine": {"color": "#eda100", "label": "", "half_life_h": 4.5, "tmax_h": None},
            "lisdexamfetamine": {"color": "#d4537e", "label": "Elvanse"},
        },
        "ha_sensors": ["lisdexamfetamine"],
        "comparisons": [{"id": "x", "name": "X", "conditions": [
            {"profile": "caffeine", "present": True, "from_h": 1, "to_h": 4}]}],
        "sleep_profile": "lisdexamfetamine",
    }
    s = validate(old)
    caf, elv = s["substances"]
    assert (caf["id"], caf["name"], caf["half_life_h"], caf["ha_sensor"]) == ("caffeine", "Caffeine", 4.5, False)
    assert [i["id"] for i in caf["items"]] == ["coffee", "espresso"] and "profile" not in caf["items"][0]
    assert (elv["id"], elv["name"], elv["profile"], elv["ha_sensor"]) == ("lisdexamfetamine", "Elvanse", "lisdexamfetamine", True)
    assert s["comparisons"][0]["conditions"][0]["substance"] == "caffeine"
    assert s["sleep_substance"] == "lisdexamfetamine"
    assert "items" not in s and "ha_sensors" not in s
    assert validate(s) == s  # converting twice changes nothing


def test_two_custom_substances_and_validation():
    s = validate({"substances": [
        {"id": "nicotine", "name": "Nicotine", "items": [{"id": "snus", "name": "Snus"}]},
        {"id": "theanine", "name": "L-theanine", "items": [{"id": "pill", "name": "Pill", "amount": 200}]},
    ], "comparisons": []})
    assert [x["profile"] for x in s["substances"]] == ["custom", "custom"]
    assert s["sleep_substance"] == "nicotine"  # caffeine is gone, so the first one
    item = {"id": "a", "name": "A"}
    with pytest.raises(Exception):  # item ids are unique across substances
        validate({"substances": [{"id": "x", "name": "X", "items": [item]}, {"id": "y", "name": "Y", "items": [item]}]})
    with pytest.raises(Exception):  # a line must use a substance in the list
        validate({"substances": [{"id": "x", "name": "X"}], "comparisons": [
            {"id": "c", "name": "C", "conditions": [{"substance": "gone", "present": True, "from_h": 0, "to_h": 1}]}]})
    with pytest.raises(Exception):
        validate({"substances": [{"id": "x", "name": "X", "profile": "nope"}]})


def e(kind, item, t, **value):
    return {"kind": kind, "item": item, "start": t, "end": None, "value": value, "status": "confirmed", "deleted": None}


def ts(day, hour):
    return datetime(2026, 11, day, int(hour), int(round((hour % 1) * 60)), tzinfo=TZ).timestamp()


def test_levels_are_relative_to_the_usual_dose():
    s = settings()
    d = doses([e("intake", "elvanse", 0.0, amount=30)], s, "lisdexamfetamine")
    peak = max(level_at(d, t * 600, s, "lisdexamfetamine") for t in range(1, 200))
    assert math.isclose(peak, 1.0, rel_tol=0.01)
    coffee = doses([e("intake", "coffee", 0.0)], s, "caffeine")  # amount from the item
    assert 70 < amount_at(coffee, 1 * H, s, "caffeine") < 90


def test_insights_comparisons_days_and_sleep():
    s = settings()
    entries = [
        e("intake", "elvanse", ts(16, 8)),
        e("intake", "coffee", ts(16, 9)),
        e("state", "overstimulated", ts(16, 11)),  # Elvanse + coffee 2 h before
        e("state", "productive", ts(16, 15)),      # Elvanse, coffee 6 h ago: no line
        e("state", "tired", ts(17, 10)),           # neither
        e("intake", "coffee", ts(17, 12)),
        e("state", "lazy", ts(17, 12.5)),          # coffee 30 min ago: not "neither"
        e("state", "creative", ts(18, 1)),         # 01:00 belongs to the 17th
        {**e("sleep", None, ts(16, 23)), "end": ts(17, 7)},
        {**e("sleep", None, ts(17, 23.5)), "end": ts(18, 6)},
    ]
    r = insights.compute(entries, s, TZ)
    lines = {c["id"]: c["counts"] for c in r["comparisons"]}
    assert lines["both"] == {"overstimulated": 1}
    assert lines["none"] == {"tired": 1, "creative": 1}
    ww = r["with_without"]["lisdexamfetamine"]
    assert ww["days_with"] == 1 and ww["days_without"] == 1
    assert ww["without"] == {"tired": 1, "lazy": 1, "creative": 1}
    assert r["since_first"]["lisdexamfetamine"][3] == {"overstimulated": 1}  # 3–4 h bin
    split = r["sleep_split"]
    assert split["less"]["nights"] == 1 and split["more"]["nights"] == 1
    assert split["less"]["avg_hours"] == 8.0 and split["more"]["avg_hours"] == 6.5
