"""Ninja Woodfire Home Assistant integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME, Platform
from homeassistant.core import HomeAssistant

from .const import CONF_ADDRESS, DOMAIN
from .coordinator import NinjaWoodfireCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR]

type NinjaWoodfireConfigEntry = ConfigEntry[NinjaWoodfireCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: NinjaWoodfireConfigEntry) -> bool:
    address: str = entry.data[CONF_ADDRESS]
    name: str = entry.data.get(CONF_NAME, "Ninja Woodfire")

    coordinator = NinjaWoodfireCoordinator(hass, address=address, name=name)
    entry.runtime_data = coordinator

    await coordinator.async_start()
    await coordinator.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: NinjaWoodfireConfigEntry) -> bool:
    coordinator: NinjaWoodfireCoordinator = entry.runtime_data
    await coordinator.async_stop()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
