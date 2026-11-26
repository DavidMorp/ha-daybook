"""The Home Assistant WebSocket client against a fake Home Assistant."""

import asyncio

from aiohttp import web

from daybook_app.ha import HomeAssistantLink


async def fake_ha(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    app = request.app
    await ws.send_json({"type": "auth_required"})
    auth = await ws.receive_json()
    if auth.get("access_token") != "token":
        await ws.send_json({"type": "auth_invalid"})
        return ws
    await ws.send_json({"type": "auth_ok"})
    async for msg in ws:
        m = msg.json()
        app["s"]["received"].append(m)
        t, i = m["type"], m["id"]
        if t == "get_config":
            await ws.send_json({"id": i, "type": "result", "success": True, "result": {"time_zone": "Europe/Amsterdam"}})
        elif t == "get_states":
            await ws.send_json({"id": i, "type": "result", "success": True, "result": [
                {"entity_id": "person.alex", "state": "home", "attributes": {"friendly_name": "Alex"}},
                {"entity_id": "zone.pool", "state": "0", "attributes": {"friendly_name": "Pool"}},
                {"entity_id": "light.kitchen", "state": "on", "attributes": {}},
            ]})
        elif t == "get_services":
            await ws.send_json({"id": i, "type": "result", "success": True, "result": {"notify": {"mobile_app_phone": {}}}})
        elif t == "subscribe_entities":
            await ws.send_json({"id": i, "type": "result", "success": True, "result": None})
            await ws.send_json({"id": i, "type": "event", "event": {"a": {"person.alex": {"s": "home", "a": {"friendly_name": "Alex"}}}}})
            app["s"]["entities_sub"] = i
            app["s"]["ws"] = ws
        elif t in ("subscribe_events", "call_service", "fire_event"):
            await ws.send_json({"id": i, "type": "result", "success": True, "result": None})
            if t == "subscribe_events":
                app["s"]["events_sub"] = i
    return ws


async def test_link_connects_tracks_states_and_calls(aiohttp_server):
    app = web.Application()
    app["s"] = {"received": []}
    app.router.add_get("/websocket", fake_ha)
    server = await aiohttp_server(app)

    link = HomeAssistantLink(str(server.make_url("/websocket")), "token")
    changes, events = [], []
    link.on_state.append(lambda eid, st: changes.append((eid, st and st["state"])))
    link.on_event.append(lambda et, data: events.append((et, data)))
    link.start()
    for _ in range(50):
        if link.connected and "entities_sub" in app["s"]:
            break
        await asyncio.sleep(0.05)
    assert link.connected
    assert link.config["time_zone"] == "Europe/Amsterdam"
    assert "light.kitchen" not in link.states and link.friendly_name("zone.pool") == "Pool"
    assert link.notify_services == ["mobile_app_phone"]
    sub = next(m for m in app["s"]["received"] if m["type"] == "subscribe_entities")
    assert sub["entity_ids"] == ["person.alex", "zone.pool"]

    await app["s"]["ws"].send_json({"id": app["s"]["entities_sub"], "type": "event", "event": {"c": {"person.alex": {"+": {"s": "Pool"}}}}})
    await app["s"]["ws"].send_json({"id": app["s"]["events_sub"], "type": "event", "event": {"event_type": "mobile_app_notification_action", "data": {"action": "DAYBOOK_CONFIRM_x"}}})
    for _ in range(50):
        if ("person.alex", "Pool") in changes and events:
            break
        await asyncio.sleep(0.05)
    assert link.states["person.alex"]["state"] == "Pool"
    assert ("person.alex", "Pool") in changes
    assert events[0][1]["action"] == "DAYBOOK_CONFIRM_x"

    await link.call_service("notify", "mobile_app_phone", {"message": "hi"})
    await link.fire_event("daybook_logged", {"id": "x"})
    types = [m["type"] for m in app["s"]["received"]]
    assert "call_service" in types and "fire_event" in types
    await link.stop()
