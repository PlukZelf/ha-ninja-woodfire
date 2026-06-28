"""Switch entities for Ninja Woodfire."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import NinjaWoodfireConfigEntry
from .const import DOMAIN
from .coordinator import NinjaWoodfireCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NinjaWoodfireConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: NinjaWoodfireCoordinator = entry.runtime_data
    async_add_entities([NinjaWoodfireConnectedSwitch(coordinator)])


class NinjaWoodfireConnectedSwitch(RestoreEntity, SwitchEntity):
    """Switch that controls whether HA maintains a BLE connection.

    When off: HA disconnects immediately and makes no further connection
    attempts. This gives the Ninja app full access to the device.

    When on: HA connects and stays connected, automatically reconnecting
    on unexpected disconnects.

    State is persisted via HA storage so that after a restart the last
    choice is respected — if the switch was off, HA does not auto-connect.
    """

    _attr_has_entity_name = True
    _attr_name = "Connected"
    _attr_icon = "mdi:bluetooth"

    def __init__(self, coordinator: NinjaWoodfireCoordinator) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{coordinator.address}_connected_switch"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.address)},
            "name": coordinator.device_name,
            "manufacturer": "Ninja",
            "model": "Woodfire Pro",
        }
        self._is_on: bool = True  # default: connected

    async def async_added_to_hass(self) -> None:
        """Restore last state on startup."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None:
            self._is_on = last_state.state == "on"
            _LOGGER.debug(
                "Restored Connected switch state: %s",
                "on" if self._is_on else "off",
            )
        # Apply the restored state
        if self._is_on:
            await self._coordinator.async_set_connected(True)
        else:
            await self._coordinator.async_set_connected(False)

    @property
    def is_on(self) -> bool:
        return self._is_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable BLE connection."""
        _LOGGER.debug("Connected switch turned ON — starting BLE connection")
        self._is_on = True
        self.async_write_ha_state()
        await self._coordinator.async_set_connected(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable BLE connection — gives Ninja app full access."""
        _LOGGER.debug("Connected switch turned OFF — disconnecting BLE")
        self._is_on = False
        self.async_write_ha_state()
        await self._coordinator.async_set_connected(False)