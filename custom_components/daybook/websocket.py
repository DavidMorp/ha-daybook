"""WebSocket API used by the Daybook panel. Admin only: this is health data."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import DOMAIN, KINDS, SIGNAL_CHANGED, STATUSES
from .data import DaybookData
from .substances import DISCLAIMER, PROFILES

_ENTRY_FIELDS = {
    vol.Optional("item"): vol.Any(None, str),
    vol.Optional("start"): vol.Coerce(float),
    vol.Optional("end"): vol.Any(None, vol.Coerce(float)),
    vol.Optional("value"): dict,
    vol.Optional("status"): vol.In(STATUSES),
    vol.Optional("note"): str,
}


def _data(hass: HomeAssistant) -> DaybookData:
    for e in hass.config_entries.async_entries(DOMAIN):
        if e.state is ConfigEntryState.LOADED:
            return e.runtime_data
    raise HomeAssistantError("Daybook is not loaded")


def _run(connection, msg, coro_fn):
    async def runner() -> None:
        try:
            result = await coro_fn()
        except (HomeAssistantError, vol.Invalid, ValueError) as err:
            connection.send_error(msg["id"], "daybook_error", str(err))
            return
        connection.send_result(msg["id"], result)
    return runner()


@websocket_api.require_admin
@websocket_api.websocket_command({
    vol.Required("type"): "daybook/entries/list",
    vol.Optional("start"): vol.Coerce(float),
    vol.Optional("end"): vol.Coerce(float),
    vol.Optional("include_deleted", default=False): bool,
})
@websocket_api.async_response
async def ws_list(hass, connection, msg) -> None:
    data = _data(hass)
    await _run(connection, msg, lambda: data.async_list(
        msg.get("start"), msg.get("end"), include_deleted=msg["include_deleted"]
    ))


@websocket_api.require_admin
@websocket_api.websocket_command({
    vol.Required("type"): "daybook/entries/create",
    vol.Required("kind"): vol.In(KINDS),
    **_ENTRY_FIELDS,
})
@websocket_api.async_response
async def ws_create(hass, connection, msg) -> None:
    data = _data(hass)
    entry = {k: msg[k] for k in ("kind", "item", "start", "end", "value", "status", "note") if k in msg}
    entry["source"] = "panel"
    await _run(connection, msg, lambda: data.async_add(entry))


@websocket_api.require_admin
@websocket_api.websocket_command({
    vol.Required("type"): "daybook/entries/update",
    vol.Required("entry_id"): str,
    **_ENTRY_FIELDS,
})
@websocket_api.async_response
async def ws_update(hass, connection, msg) -> None:
    data = _data(hass)
    changes = {k: msg[k] for k in ("item", "start", "end", "value", "status", "note") if k in msg}
    await _run(connection, msg, lambda: data.async_update(msg["entry_id"], changes))


@websocket_api.require_admin
@websocket_api.websocket_command({
    vol.Required("type"): "daybook/entries/delete",
    vol.Required("entry_id"): str,
})
@websocket_api.async_response
async def ws_delete(hass, connection, msg) -> None:
    data = _data(hass)
    await _run(connection, msg, lambda: data.async_delete(msg["entry_id"]))


@websocket_api.require_admin
@websocket_api.websocket_command({
    vol.Required("type"): "daybook/entries/restore",
    vol.Required("entry_id"): str,
})
@websocket_api.async_response
async def ws_restore(hass, connection, msg) -> None:
    data = _data(hass)
    await _run(connection, msg, lambda: data.async_restore(msg["entry_id"]))


@websocket_api.require_admin
@websocket_api.websocket_command({
    vol.Required("type"): "daybook/entries/history",
    vol.Required("entry_id"): str,
})
@websocket_api.async_response
async def ws_history(hass, connection, msg) -> None:
    data = _data(hass)
    await _run(connection, msg, lambda: hass.async_add_executor_job(data.store.history, msg["entry_id"]))


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "daybook/settings/get"})
@callback
def ws_settings_get(hass, connection, msg) -> None:
    try:
        data = _data(hass)
    except HomeAssistantError as err:
        connection.send_error(msg["id"], "daybook_error", str(err))
        return
    connection.send_result(msg["id"], {"settings": data.settings, "time_zone": hass.config.time_zone})


@websocket_api.require_admin
@websocket_api.websocket_command({
    vol.Required("type"): "daybook/settings/set",
    vol.Required("settings"): dict,
})
@websocket_api.async_response
async def ws_settings_set(hass, connection, msg) -> None:
    data = _data(hass)

    async def save() -> dict[str, Any]:
        return {"settings": await data.async_set_settings(msg["settings"])}
    await _run(connection, msg, save)


@websocket_api.require_admin
@websocket_api.websocket_command({
    vol.Required("type"): "daybook/insights",
    vol.Optional("days", default=56): vol.All(int, vol.Range(min=7, max=730)),
})
@websocket_api.async_response
async def ws_insights(hass, connection, msg) -> None:
    data = _data(hass)
    await _run(connection, msg, lambda: data.async_insights(msg["days"]))


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "daybook/substances"})
@callback
def ws_substances(hass, connection, msg) -> None:
    connection.send_result(msg["id"], {"profiles": PROFILES, "disclaimer": DISCLAIMER})


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "daybook/subscribe"})
@callback
def ws_subscribe(hass, connection, msg) -> None:
    @callback
    def forward(what: str) -> None:
        connection.send_message(websocket_api.event_message(msg["id"], {"changed": what}))

    connection.subscriptions[msg["id"]] = async_dispatcher_connect(hass, SIGNAL_CHANGED, forward)
    connection.send_result(msg["id"])


def async_register(hass: HomeAssistant) -> None:
    for handler in (
        ws_list, ws_create, ws_update, ws_delete, ws_restore, ws_history,
        ws_settings_get, ws_settings_set, ws_insights, ws_substances, ws_subscribe,
    ):
        websocket_api.async_register_command(hass, handler)
