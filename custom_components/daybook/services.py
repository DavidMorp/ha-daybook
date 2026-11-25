"""Daybook actions, for automations, scripts and ESPHome devices."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.util import dt as dt_util

from .const import DOMAIN, KINDS, STATUSES
from .data import DaybookData

LOG_SCHEMA = vol.Schema({
    vol.Required("kind"): vol.In(KINDS),
    vol.Optional("item"): cv.string,
    vol.Optional("when"): cv.datetime,
    vol.Optional("offset_minutes"): vol.All(vol.Coerce(int), vol.Range(min=-1440, max=1440)),
    vol.Optional("end"): cv.datetime,
    vol.Optional("duration_minutes"): vol.All(vol.Coerce(int), vol.Range(min=0, max=1440)),
    vol.Optional("mg"): vol.All(vol.Coerce(float), vol.Range(min=0, max=1000)),
    vol.Optional("dose"): vol.All(vol.Coerce(float), vol.Range(min=0)),
    vol.Optional("skipped"): cv.boolean,
    vol.Optional("value"): dict,
    vol.Optional("status"): vol.In(STATUSES),
    vol.Optional("note"): cv.string,
    vol.Optional("source", default="action"): vol.All(cv.string, vol.Length(max=40)),
})
UPDATE_SCHEMA = vol.Schema({
    vol.Required("id"): cv.string,
    vol.Optional("item"): cv.string,
    vol.Optional("when"): cv.datetime,
    vol.Optional("end"): cv.datetime,
    vol.Optional("value"): dict,
    vol.Optional("status"): vol.In(STATUSES),
    vol.Optional("note"): cv.string,
})
DELETE_SCHEMA = vol.Schema({vol.Required("id"): cv.string})
UNDO_SCHEMA = vol.Schema({
    vol.Optional("source"): cv.string,
    vol.Optional("within_minutes", default=10): vol.All(vol.Coerce(int), vol.Range(min=1, max=1440)),
})


def _data(hass: HomeAssistant) -> DaybookData:
    entries = [
        e for e in hass.config_entries.async_entries(DOMAIN)
        if e.state is ConfigEntryState.LOADED
    ]
    if not entries:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="not_loaded")
    return entries[0].runtime_data


def _ts(value) -> float:
    return dt_util.as_utc(dt_util.as_local(value) if value.tzinfo is None else value).timestamp()


def build_entry(call_data: dict[str, Any]) -> dict[str, Any]:
    start = dt_util.utcnow()
    if "when" in call_data:
        start = dt_util.as_utc(dt_util.as_local(call_data["when"]) if call_data["when"].tzinfo is None else call_data["when"])
    if "offset_minutes" in call_data:
        start = start + timedelta(minutes=call_data["offset_minutes"])
    end = None
    if "end" in call_data:
        end = _ts(call_data["end"])
    elif "duration_minutes" in call_data:
        end = (start + timedelta(minutes=call_data["duration_minutes"])).timestamp()
    value = dict(call_data.get("value") or {})
    if "mg" in call_data:
        value["mg"] = call_data["mg"]
    if "dose" in call_data:
        value["dose"] = call_data["dose"]
    if call_data.get("skipped"):
        value["status"] = "skipped"
    return {
        "kind": call_data["kind"],
        "item": call_data.get("item"),
        "start": start.timestamp(),
        "end": end,
        "value": value,
        "status": call_data.get("status"),
        "note": call_data.get("note", ""),
        "source": call_data.get("source", "action"),
    }


def async_register_services(hass: HomeAssistant) -> None:
    async def log(call: ServiceCall) -> ServiceResponse:
        saved = await _data(hass).async_add(build_entry(call.data))
        return {"id": saved["id"]}

    async def update(call: ServiceCall) -> ServiceResponse:
        changes: dict[str, Any] = {
            k: call.data[k] for k in ("item", "value", "status", "note") if k in call.data
        }
        if "when" in call.data:
            changes["start"] = _ts(call.data["when"])
        if "end" in call.data:
            changes["end"] = _ts(call.data["end"])
        saved = await _data(hass).async_update(call.data["id"], changes)
        return {"id": saved["id"]}

    async def delete(call: ServiceCall) -> None:
        await _data(hass).async_delete(call.data["id"])

    async def undo_last(call: ServiceCall) -> ServiceResponse:
        removed = await _data(hass).async_undo_last(call.data.get("source"), call.data["within_minutes"])
        return {"id": removed["id"] if removed else None}

    hass.services.async_register(DOMAIN, "log", log, LOG_SCHEMA, supports_response=SupportsResponse.OPTIONAL)
    hass.services.async_register(DOMAIN, "update", update, UPDATE_SCHEMA, supports_response=SupportsResponse.OPTIONAL)
    hass.services.async_register(DOMAIN, "delete", delete, DELETE_SCHEMA)
    hass.services.async_register(DOMAIN, "undo_last", undo_last, UNDO_SCHEMA, supports_response=SupportsResponse.OPTIONAL)
