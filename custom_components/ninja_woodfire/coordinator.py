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
from .crypto import decode_advert_half
from .advert_decode import decode
from .protocol import NinjaState

_LOGGER = logging.getLogger(__name__)

# If no advertisement is seen within this window, the device is treated as gone.
_SEEN_STALE_AFTER = UPDATE_INTERVAL * 2
_BUFFER_TIMEOUT = 5.0  # seconds: wait this long for second half to arrive


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
            on_single_half=self._on_single_half,
        )
        self._last_seen_monotonic: float = 0.0
        self._half_buffer: dict[int, tuple[float, bytes]] = {}

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
        _LOGGER.warning("COORDINATOR START: registering scanner for %s", self._address)
        self._scanner.start()
        self._state = NinjaState(connected=False)
        self.async_set_updated_data(self._state)
        _LOGGER.warning("COORDINATOR START: scanner registered for %s", self._address)

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
        # Clear buffer on successful decode
        self._half_buffer.clear()

    @callback
    def _on_single_half(self, half: bytes) -> None:
        """
        Handle a single encrypted half (20 or 23 bytes).
        Buffer it and wait for the complementary half within _BUFFER_TIMEOUT.
        """
        now_monotonic = time.monotonic()
        half_len = len(half)

        # Clean up stale buffered halves
        stale_keys = [
            k for k, (ts, _) in self._half_buffer.items()
            if (now_monotonic - ts) > _BUFFER_TIMEOUT
        ]
        for k in stale_keys:
            _LOGGER.debug(
                "Discarding stale buffered half for %s (len=%d)",
                self._address, k
            )
            del self._half_buffer[k]

        # Determine complement: 20 <-> 23
        complement_len = 23 if half_len == 20 else 20 if half_len == 23 else None
        if complement_len is None:
            _LOGGER.warning(
                "Unexpected half length for %s: %d (expected 20 or 23)",
                self._address, half_len
            )
            return

        if complement_len in self._half_buffer:
            # Found complement! Process together.
            complement_ts, complement_half = self._half_buffer.pop(complement_len)
            age = now_monotonic - complement_ts
            _LOGGER.debug(
                "Found buffered complement half for %s (len=%d, age=%.2fs)",
                self._address, complement_len, age
            )

            # Reconstruct in canonical order: 20-byte first, then 23-byte
            if half_len == 20:
                self._on_halves(half, complement_half)
            else:
                self._on_halves(complement_half, half)
        else:
            # Buffer this half and wait for complement.
            _LOGGER.debug(
                "Buffering incomplete half for %s (len=%d, waiting for len=%d)",
                self._address, half_len, complement_len
            )
            self._half_buffer[half_len] = (now_monotonic, half)

    async def _async_update_data(self) -> NinjaState:
        """Heartbeat: refresh the 'recently seen' flag; never fails."""
        self._state.connected = self.is_recently_seen
        return self._state
