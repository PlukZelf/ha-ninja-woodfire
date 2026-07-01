"""Switch entities for Ninja Woodfire."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import NinjaWoodfireConfigEntry
from . import commands
from .const import DOMAIN
from .coordinator import NinjaWoodfireCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NinjaWoodfireConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: NinjaWoodfireCoordinator = entry.runtime_data
    async_add_entities(
        [
            NinjaWoodfireConnectedSwitch(coordinator),
            NinjaWoodfireWoodFlavorSwitch(coordinator),
        ]
    )


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
    _attr_name = "Connection Enabled"
    _attr_icon = "mdi:bluetooth"

    def __init__(self, coordinator: NinjaWoodfireCoordinator) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{coordinator.address}_connection_enabled_switch"
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


class NinjaWoodfireWoodFlavorSwitch(
    CoordinatorEntity[NinjaWoodfireCoordinator], SwitchEntity
):
    """Wood flavor (smoke) on/off. Reflects the grill's woodFire state.

    Defaults to off; the only other state is on.
    """

    _attr_has_entity_name = True
    _attr_name = "Wood Flavor"
    _attr_icon = "mdi:fire"

    def __init__(self, coordinator: NinjaWoodfireCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.address}_wood_flavor"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.address)},
            "name": coordinator.device_name,
            "manufacturer": "Ninja",
            "model": "Woodfire Pro",
        }
        # STUB: locally remembered state, used only while
        # commands.OPTIMISTIC_CONTROLS is True. See commands.py.
        self._optimistic_on: bool | None = None

    @property
    def available(self) -> bool:
        # STUB: while optimistic, stay usable even without a live connection so
        # the UI can be exercised. Remove once decoding works.
        if commands.OPTIMISTIC_CONTROLS:
            return True
        return super().available

    @property
    def is_on(self) -> bool:
        if commands.OPTIMISTIC_CONTROLS and self._optimistic_on is not None:
            return self._optimistic_on
        if self.coordinator.data is None:
            return False
        return self.coordinator.data.wood_fire

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_set(False)

    async def _async_set(self, enabled: bool) -> None:
        # TEMPORARY: nothing is transmitted yet (see commands.OPTIMISTIC_CONTROLS).
        # Remember the state locally so the UI reflects it, then attempt the
        # (currently no-op) command. Remove the optimistic block once decoding works.
        if commands.OPTIMISTIC_CONTROLS:
            self._optimistic_on = enabled
            self.async_write_ha_state()
        await self.coordinator.async_send_command(
            lambda: commands.set_wood_flavor(enabled)
        )