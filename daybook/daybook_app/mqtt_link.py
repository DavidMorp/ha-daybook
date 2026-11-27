"""MQTT: how Home Assistant, automations and devices talk to Daybook.

Topics (prefix "daybook"):
  daybook/log          JSON: {"kind", "item", "offset_minutes", "when", "end",
                        "duration_minutes", "amount", "note", "source"}
  daybook/undo         JSON: {"source", "within_minutes"}
  daybook/press/<kind>/<item>   from the discovered button entities
  daybook/logged       published after each log: {"id", "kind", "item", "source"}
  daybook/availability online / offline
  daybook/level/<substance>     sensor states

Buttons and level sensors appear in Home Assistant through MQTT discovery.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime
from typing import TYPE_CHECKING, Any

import paho.mqtt.client as mqtt

from .const import KIND_INTAKE, KIND_STATE, KINDS
from .core import JournalError
from .model import unit_of

if TYPE_CHECKING:
    from .core import Journal

_LOGGER = logging.getLogger(__name__)
PREFIX = "daybook"
DISCOVERY = "homeassistant"
AVAILABILITY = f"{PREFIX}/availability"
KV_DISCOVERED = "mqtt_discovered"


def parse_log(payload: dict[str, Any], tz) -> dict[str, Any]:
    """Turn a daybook/log message into an entry."""
    kind = payload.get("kind")
    if kind not in KINDS:
        raise JournalError(f"Unknown kind {kind!r}")
    start = time.time()
    if payload.get("when"):
        when = datetime.fromisoformat(str(payload["when"]))
        start = (when if when.tzinfo else when.replace(tzinfo=tz)).timestamp()
    if payload.get("offset_minutes") is not None:
        start += float(payload["offset_minutes"]) * 60
    end = None
    if payload.get("end"):
        e = datetime.fromisoformat(str(payload["end"]))
        end = (e if e.tzinfo else e.replace(tzinfo=tz)).timestamp()
    elif payload.get("duration_minutes") is not None:
        end = start + float(payload["duration_minutes"]) * 60
    value: dict[str, Any] = {}
    if payload.get("amount") is not None:
        value["amount"] = float(payload["amount"])
    return {
        "kind": kind,
        "item": payload.get("item"),
        "start": start,
        "end": end,
        "value": value,
        "note": str(payload.get("note") or ""),
        "source": str(payload.get("source") or "mqtt")[:40],
    }


class MqttLink:
    def __init__(self, journal: Journal, host: str, port: int, username: str | None, password: str | None, ha=None) -> None:
        self.journal = journal
        self.ha = ha
        self.connected = False
        self._loop = asyncio.get_running_loop()
        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="daybook-app")
        if username:
            self._client.username_pw_set(username, password)
        self._client.will_set(AVAILABILITY, "offline", retain=True)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message
        self._host, self._port = host, port
        self._timer: asyncio.Task | None = None

    async def start(self) -> None:
        self._client.connect_async(self._host, self._port, keepalive=60)
        self._client.loop_start()
        self.journal.on_change(self._changed)
        self._timer = asyncio.create_task(self._tick())

    async def stop(self) -> None:
        if self._timer:
            self._timer.cancel()
        if self.connected:
            self._client.publish(AVAILABILITY, "offline", retain=True).wait_for_publish(2)
        self._client.disconnect()
        self._client.loop_stop()

    # -- paho callbacks (run in paho's thread) ---------------------------
    def _on_connect(self, client, _userdata, _flags, reason_code, _props) -> None:
        if reason_code.is_failure:
            _LOGGER.warning("MQTT connection refused: %s", reason_code)
            return
        self.connected = True
        _LOGGER.info("Connected to MQTT")
        client.subscribe([(f"{PREFIX}/log", 1), (f"{PREFIX}/undo", 1), (f"{PREFIX}/press/#", 1)])
        client.publish(AVAILABILITY, "online", retain=True)
        asyncio.run_coroutine_threadsafe(self.publish_discovery(), self._loop)

    def _on_disconnect(self, *_args) -> None:
        self.connected = False

    def _on_message(self, _client, _userdata, msg) -> None:
        asyncio.run_coroutine_threadsafe(self.handle(msg.topic, msg.payload), self._loop)

    # -- incoming --------------------------------------------------------
    async def handle(self, topic: str, payload: bytes) -> dict[str, Any] | None:
        try:
            if topic.startswith(f"{PREFIX}/press/"):
                _, _, kind, item = topic.split("/", 3)
                return await self.journal.add({"kind": kind, "item": item, "source": "button"})
            data = json.loads(payload or b"{}")
            if not isinstance(data, dict):
                raise JournalError("Expected a JSON object")
            if topic == f"{PREFIX}/log":
                return await self.journal.add(parse_log(data, self.journal.tz))
            if topic == f"{PREFIX}/undo":
                return await self.journal.undo_last(data.get("source"), int(data.get("within_minutes", 10)))
        except (JournalError, ValueError) as err:
            _LOGGER.warning("Ignored MQTT message on %s: %s", topic, err)
        return None

    # -- outgoing --------------------------------------------------------
    async def _changed(self, what: str, entry: dict[str, Any] | None) -> None:
        if what == "added" and entry:
            info = {k: entry[k] for k in ("id", "kind", "item", "source")}
            if self.connected:
                self._client.publish(f"{PREFIX}/logged", json.dumps(info))
            if self.ha is not None and self.ha.connected:
                try:
                    await self.ha.fire_event("daybook_logged", info)
                except Exception:  # noqa: BLE001
                    _LOGGER.debug("Couldn't fire daybook_logged", exc_info=True)
        if what == "settings":
            await self.publish_discovery()
        await self.publish_levels()

    async def _tick(self) -> None:
        while True:
            await asyncio.sleep(300)
            await self.publish_levels()

    def discovery_messages(self) -> dict[str, dict[str, Any]]:
        s = self.journal.settings
        device = {"identifiers": ["daybook"], "name": "Daybook", "manufacturer": "Daybook", "model": "Journal"}
        avail = {"availability_topic": AVAILABILITY}
        out: dict[str, dict[str, Any]] = {}
        for st in s["states"]:
            uid = f"daybook_state_{st['id']}"
            out[f"{DISCOVERY}/button/daybook/{uid}/config"] = {
                "name": f"Feeling {st['name'].lower()}", "unique_id": uid, "object_id": uid,
                "command_topic": f"{PREFIX}/press/{KIND_STATE}/{st['id']}", "icon": "mdi:emoticon-outline",
                "device": device, **avail,
            }
        for sub in s["substances"]:
            for it in sub["items"]:
                uid = f"daybook_took_{it['id']}"
                out[f"{DISCOVERY}/button/daybook/{uid}/config"] = {
                    "name": f"Took {it['name'].lower()}", "unique_id": uid, "object_id": uid,
                    "command_topic": f"{PREFIX}/press/{KIND_INTAKE}/{it['id']}",
                    "icon": "mdi:coffee-outline" if sub["profile"] == "caffeine" else "mdi:pill",
                    "device": device, **avail,
                }
        for sub in s["substances"]:
            if not sub.get("ha_sensor"):
                continue
            uid = f"daybook_level_{sub['id']}"
            out[f"{DISCOVERY}/sensor/daybook/{uid}/config"] = {
                "name": f"{sub['name']} in body", "unique_id": uid, "object_id": uid,
                "state_topic": f"{PREFIX}/level/{sub['id']}", "unit_of_measurement": unit_of(s, sub["id"]),
                "state_class": "measurement", "suggested_display_precision": 0,
                "icon": "mdi:chart-bell-curve-cumulative", "device": device, **avail,
            }
        return out

    async def publish_discovery(self) -> None:
        if not self.connected:
            return
        messages = self.discovery_messages()
        previous = set(await asyncio.to_thread(self.journal.store.kv_get, KV_DISCOVERED, []) or [])
        for topic, payload in messages.items():
            self._client.publish(topic, json.dumps(payload), retain=True)
        for topic in previous - set(messages):
            self._client.publish(topic, "", retain=True)  # removes the entity
        await asyncio.to_thread(self.journal.store.kv_set, KV_DISCOVERED, sorted(messages))
        await self.publish_levels()

    async def publish_levels(self) -> None:
        if not self.connected:
            return
        for sub in self.journal.settings["substances"]:
            if sub.get("ha_sensor"):
                now = await self.journal.level_now(sub["id"])
                self._client.publish(f"{PREFIX}/level/{sub['id']}", f"{now['amount']:.1f}", retain=True)
