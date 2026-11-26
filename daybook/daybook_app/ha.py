"""A small Home Assistant WebSocket client.

Inside an HA app it connects through the Supervisor proxy with the app's own
token. It keeps the states of people, zones and schedules (for sport
detection and the settings pickers), lists notify services, calls actions
and fires events. It reconnects on its own.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)
WATCHED_DOMAINS = ("person", "device_tracker", "zone", "schedule")


class HomeAssistantLink:
    def __init__(self, url: str, token: str) -> None:
        self._url = url
        self._token = token
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._next_id = 1
        self._pending: dict[int, asyncio.Future] = {}
        self._handlers: dict[int, Callable[[dict], Any]] = {}
        self._task: asyncio.Task | None = None
        self.connected = False
        self.config: dict[str, Any] = {}
        self.states: dict[str, dict[str, Any]] = {}
        self.notify_services: list[str] = []
        self.on_state: list[Callable[[str, dict[str, Any] | None], Any]] = []
        self.on_event: list[Callable[[str, dict[str, Any]], Any]] = []
        self.on_connect: list[Callable[[], Any]] = []

    # -- lifecycle -------------------------------------------------------
    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
        if self._ws:
            await self._ws.close()

    async def _run(self) -> None:
        delay = 2
        async with aiohttp.ClientSession() as session:
            while True:
                try:
                    await self._session(session)
                    delay = 2
                except asyncio.CancelledError:
                    raise
                except Exception as err:  # noqa: BLE001
                    _LOGGER.warning("Home Assistant connection lost: %s", err)
                self.connected = False
                for fut in self._pending.values():
                    if not fut.done():
                        fut.set_exception(ConnectionError("Disconnected from Home Assistant"))
                self._pending.clear()
                self._handlers.clear()
                await asyncio.sleep(delay)
                delay = min(delay * 2, 60)

    async def _session(self, session: aiohttp.ClientSession) -> None:
        async with session.ws_connect(self._url, heartbeat=30, max_msg_size=0) as ws:
            self._ws = ws
            hello = await ws.receive_json()
            if hello.get("type") != "auth_required":
                raise ConnectionError(f"Unexpected greeting: {hello}")
            await ws.send_json({"type": "auth", "access_token": self._token})
            auth = await ws.receive_json()
            if auth.get("type") != "auth_ok":
                raise ConnectionError("Home Assistant refused the token")
            reader = asyncio.create_task(self._read(ws))
            try:
                await self._prime()
                self.connected = True
                _LOGGER.info("Connected to Home Assistant")
                for cb in self.on_connect:
                    await _maybe_await(cb())
                await reader
            finally:
                reader.cancel()
                self._ws = None

    async def _prime(self) -> None:
        self.config = await self.send({"type": "get_config"})
        states = await self.send({"type": "get_states"})
        self.states = {
            s["entity_id"]: {"state": s["state"], "attributes": s.get("attributes", {})}
            for s in states if s["entity_id"].split(".", 1)[0] in WATCHED_DOMAINS
        }
        await self.refresh_services()
        await self.send({"type": "subscribe_entities", "entity_ids": sorted(self.states)}, handler=self._entities)
        await self.send(
            {"type": "subscribe_events", "event_type": "mobile_app_notification_action"},
            handler=self._event,
        )

    async def refresh_services(self) -> None:
        services = await self.send({"type": "get_services"})
        self.notify_services = sorted((services.get("notify") or {}).keys())

    # -- messages --------------------------------------------------------
    async def send(self, msg: dict[str, Any], handler: Callable[[dict], Any] | None = None, timeout: float = 30) -> Any:
        if self._ws is None:
            raise ConnectionError("Not connected to Home Assistant")
        msg_id = self._next_id
        self._next_id += 1
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[msg_id] = fut
        if handler:
            self._handlers[msg_id] = handler
        await self._ws.send_json({**msg, "id": msg_id})
        return await asyncio.wait_for(fut, timeout)

    async def _read(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        async for raw in ws:
            if raw.type != aiohttp.WSMsgType.TEXT:
                if raw.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    break
                continue
            msg = raw.json()
            if msg.get("type") == "result":
                fut = self._pending.pop(msg["id"], None)
                if fut and not fut.done():
                    if msg.get("success"):
                        fut.set_result(msg.get("result"))
                    else:
                        fut.set_exception(RuntimeError(msg.get("error", {}).get("message", "Request failed")))
            elif msg.get("type") == "event":
                handler = self._handlers.get(msg["id"])
                if handler:
                    try:
                        await _maybe_await(handler(msg["event"]))
                    except Exception:  # noqa: BLE001
                        _LOGGER.exception("Event handler failed")

    async def _entities(self, event: dict[str, Any]) -> None:
        """Apply subscribe_entities updates (compressed state format)."""
        for entity_id, s in (event.get("a") or {}).items():
            self._set(entity_id, {"state": s.get("s"), "attributes": s.get("a", {})})
        for entity_id, diff in (event.get("c") or {}).items():
            current = dict(self.states.get(entity_id) or {"state": None, "attributes": {}})
            plus = diff.get("+") or {}
            if "s" in plus:
                current["state"] = plus["s"]
            if "a" in plus:
                current["attributes"] = {**current.get("attributes", {}), **plus["a"]}
            for key in (diff.get("-") or {}).get("a", []):
                current.get("attributes", {}).pop(key, None)
            self._set(entity_id, current)
        for entity_id in event.get("r") or []:
            self.states.pop(entity_id, None)
            await self._notify_state(entity_id, None)

    def _set(self, entity_id: str, state: dict[str, Any]) -> None:
        old = self.states.get(entity_id)
        self.states[entity_id] = state
        if old is None or old.get("state") != state.get("state"):
            asyncio.get_running_loop().create_task(self._notify_state(entity_id, state))

    async def _notify_state(self, entity_id: str, state: dict[str, Any] | None) -> None:
        for cb in self.on_state:
            try:
                await _maybe_await(cb(entity_id, state))
            except Exception:  # noqa: BLE001
                _LOGGER.exception("State listener failed")

    async def _event(self, event: dict[str, Any]) -> None:
        for cb in self.on_event:
            await _maybe_await(cb(event.get("event_type", ""), event.get("data") or {}))

    # -- actions ---------------------------------------------------------
    async def call_service(self, domain: str, service: str, data: dict[str, Any]) -> None:
        await self.send({"type": "call_service", "domain": domain, "service": service, "service_data": data})

    async def fire_event(self, event_type: str, data: dict[str, Any]) -> None:
        await self.send({"type": "fire_event", "event_type": event_type, "event_data": data})

    def friendly_name(self, entity_id: str) -> str:
        state = self.states.get(entity_id) or {}
        return (state.get("attributes") or {}).get("friendly_name") or entity_id


async def _maybe_await(value: Any) -> Any:
    if asyncio.iscoroutine(value) or isinstance(value, asyncio.Future):
        return await value
    return value
