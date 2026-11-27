"""The app: journal, web API, MQTT messages and sport detection."""

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from daybook_app.core import Journal, JournalError
from daybook_app.mqtt_link import MqttLink, parse_log
from daybook_app.server import create_app
from daybook_app.sport import SportTracker, window_overlap_seconds

TZ = ZoneInfo("Europe/Amsterdam")


@pytest.fixture
async def journal(tmp_path):
    j = Journal(tmp_path, "Europe/Amsterdam")
    await j.start()
    yield j
    await j.stop()


async def test_journal_fills_amount_and_rejects_unknown_items(journal):
    events = []
    journal.on_change(lambda what, entry: events.append(what))
    saved = await journal.add({"kind": "intake", "item": "coffee"})
    assert saved["value"] == {"amount": 90, "unit": "mg"}
    with pytest.raises(JournalError):
        await journal.add({"kind": "state", "item": "nope"})
    await journal.undo_last(None)
    assert events == ["added", "deleted"]
    assert await journal.list() == []


async def test_web_api(aiohttp_client, journal):
    client = await aiohttp_client(create_app(journal))
    page = await client.get("/")
    assert page.status == 200 and "daybook-app" in await page.text()
    assert (await client.get("/static/daybook.js")).status == 200
    ws = await client.ws_connect("/api/ws")
    await ws.send_json({"id": 1, "type": "daybook/subscribe"})
    assert (await ws.receive_json())["success"]
    await ws.send_json({"id": 2, "type": "daybook/entries/create", "kind": "state", "item": "tired"})
    msgs = [await ws.receive_json(), await ws.receive_json()]
    result = next(m for m in msgs if m["type"] == "result")
    assert result["success"] and result["result"]["source"] == "panel"
    assert any(m["type"] == "event" and m["event"]["changed"] == "added" for m in msgs)
    await ws.send_json({"id": 3, "type": "daybook/entries/create", "kind": "state", "item": "nope"})
    while (m := await ws.receive_json())["type"] != "result":
        pass
    assert not m["success"] and "no state" in m["error"]["message"]
    await ws.send_json({"id": 4, "type": "daybook/settings/set", "settings": {"states": []}})
    while (m := await ws.receive_json())["type"] != "result":
        pass
    assert not m["success"]
    await ws.close()


async def test_only_ingress_proxy_may_connect(aiohttp_client, journal):
    client = await aiohttp_client(create_app(journal, allowed_ips={"172.30.32.2"}))
    assert (await client.get("/")).status == 403


def test_parse_log_message():
    when = datetime(2026, 11, 24, 8, 0, tzinfo=TZ).timestamp()
    entry = parse_log({"kind": "intake", "item": "coffee", "when": "2026-11-24T08:30:00", "offset_minutes": -30,
                       "amount": 120, "source": "box"}, TZ)
    assert entry["start"] == when and entry["value"] == {"amount": 120.0} and entry["source"] == "box"
    sport = parse_log({"kind": "sport", "item": "Rowing", "when": "2026-11-24T07:00:00", "duration_minutes": 90}, TZ)
    assert sport["end"] - sport["start"] == 5400
    with pytest.raises(JournalError):
        parse_log({"kind": "med"}, TZ)


async def test_mqtt_messages_and_discovery(journal):
    link = MqttLink(journal, "localhost", 1883, None, None)
    saved = await link.handle("daybook/log", json.dumps({"kind": "intake", "item": "espresso", "source": "box"}).encode())
    assert saved["item"] == "espresso" and saved["value"]["amount"] == 65
    pressed = await link.handle("daybook/press/state/tired", b"PRESS")
    assert pressed["source"] == "button"
    undone = await link.handle("daybook/undo", json.dumps({"source": "button"}).encode())
    assert undone["id"] == pressed["id"]
    assert await link.handle("daybook/log", b"not json") is None
    topics = link.discovery_messages()
    assert "homeassistant/button/daybook/daybook_took_coffee/config" in topics
    sensor = topics["homeassistant/sensor/daybook/daybook_level_caffeine/config"]
    assert sensor["unit_of_measurement"] == "mg" and sensor["state_topic"] == "daybook/level/caffeine"


class FakeHA:
    connected = True

    def __init__(self):
        self.states = {"zone.pool": {"state": "0", "attributes": {"friendly_name": "Pool"}},
                       "person.alex": {"state": "home", "attributes": {}}}
        self.on_state, self.on_event, self.on_connect, self.calls = [], [], [], []

    def friendly_name(self, entity_id):
        return self.states[entity_id]["attributes"].get("friendly_name", entity_id)

    async def call_service(self, domain, service, data):
        self.calls.append((domain, service, data))


def local(day, hour, minute=0):
    return datetime(2026, 11, day, hour, minute, tzinfo=TZ).timestamp()


async def test_sport_zone_suggests_and_confirms(journal):
    ha = FakeHA()
    await journal.set_settings({**journal.settings, "notify_service": "mobile_app_phone", "sport_zones": [{
        "id": "pool", "zone": "zone.pool", "person": "person.alex", "activity": "Water polo", "min_minutes": 60,
        "windows": [{"weekdays": [1, 4], "from": "19:30", "to": "21:30"}]}]})
    tracker = SportTracker(journal, ha)
    await tracker.start()

    async def move(state, ts):
        ha.states["person.alex"] = {"state": state, "attributes": {}}
        await tracker.state_changed("person.alex", ha.states["person.alex"], now=ts)

    await move("Pool", local(24, 18, 50))      # Tuesday, early
    await move("not_home", local(24, 21, 40))  # 2 h inside the window
    await move("Pool", local(23, 18, 50))      # Monday: no window
    await move("not_home", local(23, 21, 40))
    sport = [x for x in await journal.list() if x["kind"] == "sport"]
    assert len(sport) == 1 and sport[0]["status"] == "draft"
    assert ha.calls and ha.calls[0][1] == "mobile_app_phone"

    await tracker.event("mobile_app_notification_action", {"action": f"DAYBOOK_CONFIRM_{sport[0]['id']}"})
    assert (await journal.get(sport[0]["id"]))["status"] == "confirmed"


def test_window_overlap_crossing_midnight():
    w = [{"weekdays": [5], "from": "23:00", "to": "01:00"}]
    assert window_overlap_seconds(local(28, 22, 30), local(29, 2), w, TZ) == 2 * 3600


async def test_old_settings_are_converted_and_saved_on_start(tmp_path):
    j = Journal(tmp_path, "Europe/Amsterdam")
    await j.start()
    old = {"items": [{"id": "ritalin", "name": "Ritalin", "profile": "mph_ir", "amount": 10, "unit": "mg"}],
           "substances": {"mph_ir": {"color": "#534ab7", "label": ""}}, "ha_sensors": ["mph_ir"],
           "comparisons": [], "sleep_profile": "mph_ir"}
    j.store.kv_set("settings", old)
    await j.stop()
    j = Journal(tmp_path, "Europe/Amsterdam")
    await j.start()
    stored = j.store.kv_get("settings")
    assert stored == j.settings and "items" not in stored
    assert stored["substances"][0]["items"][0]["id"] == "ritalin"
    saved = await j.add({"kind": "intake", "item": "ritalin"})  # the same item id still works
    assert saved["value"]["amount"] == 10
    assert (await j.level_now("mph_ir"))["amount"] >= 0
    await j.stop()
