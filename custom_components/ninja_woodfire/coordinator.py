"""Data update coordinator for the Ninja Woodfire Pro Connect XL integration.

Keeps a NinjaState up to date by receiving BLE notifications from the
NinjaWoodfireClient and propagating updates to Home Assistant entities.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .bluetooth import NinjaWoodfireClient
from .const import DOMAIN, NINJA_INDICATE_UUID, NINJA_NOTIFY_UUID, UPDATE_INTERVAL
from .protocol import NinjaState, apply_indicate, apply_notify

_LOGGER = logging.getLogger(__name__)


class NinjaWoodfireCoordinator(DataUpdateCoordinator[NinjaState]):
    """Coordinator that owns the BLE client and holds the current device state."""

    def __init__(self, hass: HomeAssistant, address: str, name: str) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{address}",
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )
        self._address = address
        self._device_name = name
        self._state = NinjaState()
        self._client = NinjaWoodfireClient(
            address=address,
            on_data=self._on_ble_data,
        )

    @property
    def device_name(self) -> str:
        return self._device_name

    @property
    def address(self) -> str:
        return self._address

    async def async_start(self) -> None:
        """Connect the BLE client. Called once from __init__.py setup."""
        try:
            await self._client.start()
            self._state = NinjaState(connected=True)
            self.async_set_updated_data(self._state)
        except Exception as err:
            _LOGGER.error("Failed to connect to %s: %s", self._address, err)
            self._state = NinjaState(connected=False)
            self.async_set_updated_data(self._state)

    async def async_stop(self) -> None:
        """Disconnect. Called from __init__.py unload."""
        await self._client.stop()

    @callback
    def _on_ble_data(self, uuid: str, payload: bytes) -> None:
        """Handle incoming BLE notification or indication."""
        if uuid == NINJA_INDICATE_UUID:
            self._state = apply_indicate(self._state, payload)
        elif uuid == NINJA_NOTIFY_UUID:
            self._state = apply_notify(self._state, payload)
        else:
            _LOGGER.debug("Unexpected notification from %s", uuid)
            return

        self._state = NinjaState(
            raw_indicate=self._state.raw_indicate,
            raw_notify=self._state.raw_notify,
            connected=self._client.is_connected,
            power_on=self._state.power_on,
            cooking_mode=self._state.cooking_mode,
            target_temp_c=self._state.target_temp_c,
            probe_temp_c=self._state.probe_temp_c,
            timer_remaining_s=self._state.timer_remaining_s,
            error_code=self._state.error_code,
        )
        self.async_set_updated_data(self._state)

    async def _async_update_data(self) -> NinjaState:
        """Heartbeat poll — reconnect if disconnected."""
        if not self._client.is_connected:
            _LOGGER.debug("Heartbeat: not connected, attempting reconnect")
            try:
                await self._client.start()
                self._state = NinjaState(
                    raw_indicate=self._state.raw_indicate,
                    raw_notify=self._state.raw_notify,
                    connected=True,
                    power_on=self._state.power_on,
                    cooking_mode=self._state.cooking_mode,
                    target_temp_c=self._state.target_temp_c,
                    probe_temp_c=self._state.probe_temp_c,
                    timer_remaining_s=self._state.timer_remaining_s,
                    error_code=self._state.error_code,
                )
            except Exception as err:
                raise UpdateFailed(f"Reconnect failed: {err}") from err

        return self._state
