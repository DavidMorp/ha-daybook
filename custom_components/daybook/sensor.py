"""Caffeine estimate sensor.

It exposes only the current estimate, never the journal itself, so other
automations can use it (for example a "too late for coffee" reminder). It can
be turned off in Settings.
"""

from __future__ import annotations

from datetime import timedelta

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval

from .const import SIGNAL_CHANGED
from .entity import DaybookEntity


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    data = entry.runtime_data
    if data.settings["caffeine_sensor"]:
        async_add_entities([CaffeineSensor(data)])


class CaffeineSensor(DaybookEntity, SensorEntity):
    _attr_native_unit_of_measurement = "mg"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0
    _attr_icon = "mdi:coffee-to-go-outline"
    _attr_name = "Caffeine estimate"

    def __init__(self, data) -> None:
        super().__init__(data)
        self._attr_unique_id = f"{data.entry.entry_id}_caffeine"

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(self.hass, SIGNAL_CHANGED, self._changed))
        self.async_on_remove(
            async_track_time_interval(self.hass, self._tick, timedelta(minutes=5))
        )
        await self._refresh()

    @callback
    def _changed(self, what: str) -> None:
        self.hass.async_create_task(self._refresh())

    async def _tick(self, _now) -> None:
        await self._refresh()

    async def _refresh(self) -> None:
        self._attr_native_value = round(await self.data.async_caffeine_now(), 1)
        self.async_write_ha_state()
