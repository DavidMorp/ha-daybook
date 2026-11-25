"""Daybook: a private, local journal for Home Assistant."""

from __future__ import annotations

import json
from pathlib import Path

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from . import websocket
from .const import DB_FILENAME, DOMAIN, PANEL_COMPONENT, PANEL_URL_PATH, STATIC_URL
from .data import DaybookData
from .services import async_register_services
from .sport import SportTracker
from .store import DaybookStore

PLATFORMS = [Platform.BUTTON, Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
FRONTEND_DIR = Path(__file__).parent / "frontend"

type DaybookConfigEntry = ConfigEntry[DaybookData]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async_register_services(hass)
    websocket.async_register(hass)
    await hass.http.async_register_static_paths(
        [StaticPathConfig(STATIC_URL, str(FRONTEND_DIR), cache_headers=False)]
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: DaybookConfigEntry) -> bool:
    store = DaybookStore(hass.config.path(DB_FILENAME))
    await hass.async_add_executor_job(store.open)
    data = DaybookData(hass, entry, store)
    await data.async_load()
    entry.runtime_data = data

    data.sport = SportTracker(data)
    await data.sport.async_start()

    version = await hass.async_add_executor_job(_version)
    if PANEL_URL_PATH not in hass.data.get(frontend.DATA_PANELS, {}):
        await panel_custom.async_register_panel(
            hass,
            webcomponent_name=PANEL_COMPONENT,
            frontend_url_path=PANEL_URL_PATH,
            module_url=f"{STATIC_URL}/daybook-panel.js?v={version}",
            sidebar_title="Daybook",
            sidebar_icon="mdi:notebook-heart-outline",
            require_admin=True,
            config={},
        )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: DaybookConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        data = entry.runtime_data
        data.sport.async_stop()
        frontend.async_remove_panel(hass, PANEL_URL_PATH, warn_if_unknown=False)
        await hass.async_add_executor_job(data.store.close)
    return unloaded


def _version() -> str:
    manifest = json.loads((Path(__file__).parent / "manifest.json").read_text())
    stamp = int((FRONTEND_DIR / "daybook-panel.js").stat().st_mtime)
    return f"{manifest['version']}-{stamp}"
