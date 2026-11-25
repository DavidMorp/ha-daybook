"""Quick-log buttons: one per state, drink and med (taken and skipped).

Buttons let you log from dashboards, phone widgets, voice and NFC tags
without writing an automation. Their state is only the last press time.
"""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import KIND_CAFFEINE, KIND_MED, KIND_STATE, MED_SKIPPED, MED_TAKEN
from .entity import DaybookEntity


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    data = entry.runtime_data
    s = data.settings
    entities: list[LogButton] = []
    for st in s["states"]:
        entities.append(LogButton(data, KIND_STATE, st["id"], f"Feeling {st['name'].lower()}", "mdi:emoticon-outline"))
    for dr in s["drinks"]:
        entities.append(LogButton(data, KIND_CAFFEINE, dr["id"], dr["name"], "mdi:coffee-outline"))
    for med in s["meds"]:
        entities.append(LogButton(data, KIND_MED, med["id"], f"{med['name']} taken", "mdi:pill", MED_TAKEN))
        entities.append(LogButton(data, KIND_MED, med["id"], f"{med['name']} skipped", "mdi:pill-off", MED_SKIPPED))
    async_add_entities(entities)


class LogButton(DaybookEntity, ButtonEntity):
    def __init__(self, data, kind: str, item: str, name: str, icon: str, med_status: str | None = None) -> None:
        super().__init__(data)
        self._kind = kind
        self._item = item
        self._med_status = med_status
        suffix = f"_{med_status}" if med_status else ""
        self._attr_unique_id = f"{data.entry.entry_id}_log_{kind}_{item}{suffix}"
        self._attr_name = f"Log {name}"
        self._attr_icon = icon

    async def async_press(self) -> None:
        value = {"status": self._med_status} if self._med_status else {}
        await self.data.async_add({
            "kind": self._kind, "item": self._item, "value": value, "source": "button",
        })
