"""Data update coordinator for the Ninja Woodfire integration.

Passive advertisement scanning only: no GATT connection. The coordinator
registers a passive BLE callback, decodes each advertisement into a
NinjaState, and tracks device presence by advertisement recency.
"""

from __future__ import annotations

import logging
import time
from datetime import timedelta

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .advert import build_state_from_halves
from .bluetooth import NinjaWoodfireScanner
from .const import DOMAIN, UPDATE_INTERVAL
from .protocol import NinjaState

_LOGGER = logging.getLogger(__name__)

# If no advertisement is seen within this window, the device is treated as gone.
_SEEN_STALE_AFTER = UPDATE_INTERVAL * 2


class NinjaWoodfireCoordinator(DataUpdateCoordinator[NinjaState]):
    """Owns the passive scanner and holds the current decoded device state."""

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
        self._scanner = NinjaWoodfireScanner(
            hass=hass,
            address=address,
            on_halves=self._on_halves,
        )
        self._last_seen_monotonic: float = 0.0

    @property
    def device_name(self) -> str:
        return self._device_name

    @property
    def address(self) -> str:
        return self._address

    @property
    def is_recently_seen(self) -> bool:
        """True iff an advertisement was decoded recently."""
        if not self._last_seen_monotonic:
            return False
        return (time.monotonic() - self._last_seen_monotonic) <= _SEEN_STALE_AFTER

    async def async_start(self) -> None:
        """Register the passive scanner. Called from __init__.py setup."""
        self._scanner.start()
        self._state = NinjaState(connected=False)
        self.async_set_updated_data(self._state)
        _LOGGER.debug("Passive scanner started for %s", self._address)

    async def async_stop(self) -> None:
        """Unregister the scanner. Called from __init__.py unload."""
        self._scanner.stop()

    @callback
    def _on_halves(self, half1: bytes, half2: bytes) -> None:
        """Handle a decoded advertisement (two raw encrypted halves)."""
        try:
            new_state = build_state_from_halves(half1, half2)
        except ValueError as err:
            _LOGGER.debug("Advert decode failed for %s: %s", self._address, err)
            return
        self._last_seen_monotonic = time.monotonic()
        new_state.connected = True
        self._state = new_state
        self.async_set_updated_data(self._state)

    async def _async_update_data(self) -> NinjaState:
        """Heartbeat: refresh the 'recently seen' flag; never fails."""
        self._state.connected = self.is_recently_seen
        return self._state
