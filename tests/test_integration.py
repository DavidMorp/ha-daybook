"""Daybook running inside a Home Assistant test instance."""

from datetime import timedelta
import time

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.daybook.const import DOMAIN
from custom_components.daybook.sport import window_overlap_seconds


@pytest.fixture
async def entry(hass: HomeAssistant, tmp_path):
    hass.config.config_dir = str(tmp_path)
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    assert await async_setup_component(hass, "http", {})
    e = MockConfigEntry(domain=DOMAIN, title="Daybook", data={})
    e.add_to_hass(hass)
    assert await hass.config_entries.async_setup(e.entry_id)
    await hass.async_block_till_done()
    return e


async def test_setup_creates_panel_buttons_and_sensor(hass, entry):
    assert "daybook" in hass.data["frontend_panels"]
    assert hass.states.get("button.daybook_log_feeling_productive") is not None
    assert hass.states.get("button.daybook_log_coffee") is not None
    assert float(hass.states.get("sensor.daybook_caffeine_estimate").state) == 0


async def test_log_action_and_undo(hass, entry):
    events = []
    hass.bus.async_listen("daybook_logged", lambda e: events.append(e.data))
    res = await hass.services.async_call(
        DOMAIN, "log", {"kind": "caffeine", "item": "coffee", "offset_minutes": -60, "source": "box"},
        blocking=True, return_response=True,
    )
    await hass.async_block_till_done()
    data = entry.runtime_data
    saved = await hass.async_add_executor_job(data.store.get, res["id"])
    assert saved["value"] == {"mg": 90} and saved["source"] == "box"
    assert abs(saved["start"] - (time.time() - 3600)) < 5
    assert events and events[0]["kind"] == "caffeine" and "mg" not in events[0]
    assert float(hass.states.get("sensor.daybook_caffeine_estimate").state) > 50

    res = await hass.services.async_call(DOMAIN, "undo_last", {"source": "box"}, blocking=True, return_response=True)
    assert res["id"] == saved["id"]

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "log", {"kind": "state", "item": "nope"}, blocking=True)


async def test_button_press_and_websocket(hass, entry, hass_ws_client):
    await hass.services.async_call("button", "press", {"entity_id": "button.daybook_log_feeling_tired"}, blocking=True)
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": "daybook/entries/list"})
    msg = await client.receive_json()
    assert msg["success"] and [e["item"] for e in msg["result"]] == ["tired"]
    entry_id = msg["result"][0]["id"]

    await client.send_json({"id": 2, "type": "daybook/entries/update", "entry_id": entry_id, "item": "lazy"})
    msg = await client.receive_json()
    assert msg["success"] and msg["result"]["item"] == "lazy"

    await client.send_json({"id": 3, "type": "daybook/settings/get"})
    settings = (await client.receive_json())["result"]["settings"]
    settings["meds"] = [{"id": "elvanse", "name": "Elvanse", "dose": 30, "profile": "lisdexamfetamine"}]
    await client.send_json({"id": 4, "type": "daybook/settings/set", "settings": settings})
    msg = await client.receive_json()
    assert msg["success"], msg
    await hass.async_block_till_done()
    assert hass.states.get("button.daybook_log_elvanse_skipped") is not None

    await client.send_json({"id": 5, "type": "daybook/settings/set", "settings": {**settings, "states": []}})
    msg = await client.receive_json()
    assert not msg["success"]

    await client.send_json({"id": 6, "type": "daybook/insights", "days": 28})
    msg = await client.receive_json()
    assert msg["success"] and msg["result"]["n_states"] == 1

    await client.send_json({"id": 7, "type": "daybook/substances"})
    msg = await client.receive_json()
    assert "lisdexamfetamine" in msg["result"]["profiles"]


async def test_websocket_requires_admin(hass, entry, hass_ws_client, hass_read_only_access_token):
    client = await hass_ws_client(hass, hass_read_only_access_token)
    await client.send_json({"id": 1, "type": "daybook/entries/list"})
    msg = await client.receive_json()
    assert not msg["success"] and msg["error"]["code"] == "unauthorized"


async def test_sport_zone_creates_draft(hass, entry, hass_ws_client, freezer):
    hass.states.async_set("zone.pool", "0", {"friendly_name": "Pool", "latitude": 0, "longitude": 0, "radius": 50})
    hass.states.async_set("person.alex", "home")
    data = entry.runtime_data
    settings = dict(data.settings)
    settings["sport_zones"] = [{
        "id": "water_polo", "zone": "zone.pool", "person": "person.alex", "activity": "Water polo",
        "min_minutes": 60, "windows": [{"weekdays": [1, 4], "from": "19:30", "to": "21:30"}],
    }]
    await data.async_set_settings(settings)
    await hass.async_block_till_done()

    # Tuesday 18:50 local: arrive early, leave 21:40. 2 h inside the window.
    freezer.move_to("2026-11-24T17:50:00+00:00")
    hass.states.async_set("person.alex", "Pool")
    await hass.async_block_till_done()
    freezer.move_to("2026-11-24T20:40:00+00:00")
    hass.states.async_set("person.alex", "not_home")
    await hass.async_block_till_done()
    entries = await data.async_list(None, None)
    sport = [e for e in entries if e["kind"] == "sport"]
    assert len(sport) == 1 and sport[0]["status"] == "draft" and sport[0]["item"] == "Water polo"

    # Same place on a Monday: outside every window, nothing logged.
    freezer.move_to("2026-11-23T17:50:00+00:00")
    hass.states.async_set("person.alex", "Pool")
    await hass.async_block_till_done()
    freezer.move_to("2026-11-23T20:40:00+00:00")
    hass.states.async_set("person.alex", "not_home")
    await hass.async_block_till_done()
    assert len([e for e in await data.async_list(None, None) if e["kind"] == "sport"]) == 1

    # Confirm from a notification action.
    hass.bus.async_fire("mobile_app_notification_action", {"action": f"DAYBOOK_CONFIRM_{sport[0]['id']}"})
    await hass.async_block_till_done()
    assert (await hass.async_add_executor_job(data.store.get, sport[0]["id"]))["status"] == "confirmed"


def test_window_overlap_crossing_midnight():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    tz = ZoneInfo("Europe/Amsterdam")
    w = [{"weekdays": [5], "from": "23:00", "to": "01:00"}]  # Saturday night
    start = datetime(2026, 11, 28, 22, 30, tzinfo=tz).timestamp()
    end = datetime(2026, 11, 29, 2, 0, tzinfo=tz).timestamp()
    assert window_overlap_seconds(start, end, w, tz) == 2 * 3600


async def test_unload(hass, entry):
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert "daybook" not in hass.data.get("frontend_panels", {})
