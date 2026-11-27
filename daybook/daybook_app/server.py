"""Web server for the Daybook panel, shown in Home Assistant through ingress."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aiohttp import WSMsgType, web

from .const import KINDS, STATUSES
from .core import Journal, JournalError
from .settings import merge_defaults
from .substances import DISCLAIMER, PROFILES

if TYPE_CHECKING:
    from .ha import HomeAssistantLink
    from .mqtt_link import MqttLink

_LOGGER = logging.getLogger(__name__)
WEB_DIR = Path(__file__).parent / "web"
ENTRY_FIELDS = ("item", "start", "end", "value", "status", "note")


def _num(value: Any, name: str, optional: bool = True) -> float | None:
    if value is None and optional:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise JournalError(f"{name} must be a number")
    return float(value)


def _entry_fields(msg: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in ENTRY_FIELDS:
        if key not in msg:
            continue
        value = msg[key]
        if key in ("start", "end"):
            value = _num(value, key, optional=key == "end")
        elif key == "value" and not isinstance(value, dict):
            raise JournalError("value must be an object")
        elif key == "status" and value not in STATUSES:
            raise JournalError("Unknown status")
        elif key in ("item", "note") and value is not None and not isinstance(value, str):
            raise JournalError(f"{key} must be text")
        out[key] = value
    return out


class Api:
    def __init__(self, journal: Journal, ha: HomeAssistantLink | None, mqtt: MqttLink | None) -> None:
        self.journal = journal
        self.ha = ha
        self.mqtt = mqtt

    async def handle(self, msg: dict[str, Any]) -> Any:
        j = self.journal
        t = msg.get("type")
        if t == "daybook/entries/list":
            return await j.list(_num(msg.get("start"), "start"), _num(msg.get("end"), "end"),
                                include_deleted=bool(msg.get("include_deleted")))
        if t == "daybook/entries/create":
            if msg.get("kind") not in KINDS:
                raise JournalError("Unknown kind")
            return await j.add({"kind": msg["kind"], **_entry_fields(msg), "source": "panel"})
        if t == "daybook/entries/update":
            return await j.update(str(msg.get("entry_id")), _entry_fields(msg))
        if t == "daybook/entries/delete":
            return await j.delete(str(msg.get("entry_id")))
        if t == "daybook/entries/restore":
            return await j.restore(str(msg.get("entry_id")))
        if t == "daybook/entries/history":
            return await j.history(str(msg.get("entry_id")))
        if t == "daybook/settings/get":
            return {"settings": j.settings}
        if t == "daybook/settings/set":
            if not isinstance(msg.get("settings"), dict):
                raise JournalError("settings must be an object")
            return {"settings": await j.set_settings(msg["settings"])}
        if t == "daybook/settings/normalize":
            # Imported files may come from an older version: convert, don't save.
            if not isinstance(msg.get("settings"), dict):
                raise JournalError("settings must be an object")
            return {"settings": merge_defaults(msg["settings"])}
        if t == "daybook/insights":
            days = int(_num(msg.get("days", 56), "days") or 56)
            return await j.insights(max(7, min(days, 730)))
        if t == "daybook/substances":
            return {"profiles": PROFILES, "disclaimer": DISCLAIMER}
        if t == "daybook/ha":
            return self.ha_info()
        raise JournalError(f"Unknown command {t}")

    def ha_info(self) -> dict[str, Any]:
        ha = self.ha
        if ha is None:
            return {"connected": False, "mqtt": bool(self.mqtt and self.mqtt.connected), "entities": {}, "notify": []}
        entities = {
            eid: ha.friendly_name(eid) for eid in sorted(ha.states)
            if eid.split(".", 1)[0] in ("zone", "person", "device_tracker", "schedule")
        }
        return {
            "connected": ha.connected,
            "mqtt": bool(self.mqtt and self.mqtt.connected),
            "entities": entities,
            "notify": ha.notify_services,
        }


def create_app(journal: Journal, ha=None, mqtt=None, allowed_ips: set[str] | None = None) -> web.Application:
    api = Api(journal, ha, mqtt)

    @web.middleware
    async def only_ingress(request: web.Request, handler):
        # Inside Home Assistant only the Supervisor's ingress proxy may connect.
        if allowed_ips is not None and request.remote not in allowed_ips:
            raise web.HTTPForbidden()
        return await handler(request)

    async def index(_request: web.Request) -> web.StreamResponse:
        return web.FileResponse(WEB_DIR / "index.html", headers={"Cache-Control": "no-cache"})

    async def websocket(request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=30)
        await ws.prepare(request)
        unsubscribe = []

        async def send(payload: dict[str, Any]) -> None:
            if not ws.closed:
                await ws.send_str(json.dumps(payload))

        async def run(msg: dict[str, Any]) -> None:
            msg_id = msg.get("id")
            if msg.get("type") == "daybook/subscribe":
                async def forward(what: str, _entry: Any) -> None:
                    await send({"id": msg_id, "type": "event", "event": {"changed": what}})
                unsubscribe.append(journal.on_change(forward))
                await send({"id": msg_id, "type": "result", "success": True, "result": None})
                return
            try:
                result = await api.handle(msg)
                await send({"id": msg_id, "type": "result", "success": True, "result": result})
            except JournalError as err:
                await send({"id": msg_id, "type": "result", "success": False, "error": {"message": str(err)}})
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Request failed: %s", msg.get("type"))
                await send({"id": msg_id, "type": "result", "success": False, "error": {"message": "Something went wrong; see the app log."}})

        try:
            async for raw in ws:
                if raw.type == WSMsgType.TEXT:
                    try:
                        msg = json.loads(raw.data)
                    except ValueError:
                        continue
                    asyncio.create_task(run(msg))
                elif raw.type == WSMsgType.ERROR:
                    break
        finally:
            for unsub in unsubscribe:
                unsub()
        return ws

    app = web.Application(middlewares=[only_ingress])
    app.router.add_get("/", index)
    app.router.add_get("/api/ws", websocket)
    app.router.add_static("/static/", WEB_DIR, append_version=False)
    app["api"] = api
    return app
