"""Shared entity base."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN
from .data import DaybookData


class DaybookEntity(Entity):
    _attr_has_entity_name = True

    def __init__(self, data: DaybookData) -> None:
        self.data = data
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, data.entry.entry_id)},
            name="Daybook",
            entry_type=DeviceEntryType.SERVICE,
        )
