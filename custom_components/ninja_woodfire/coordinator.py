"""Data update coordinator for the Ninja Woodfire integration."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from datetime import timedelta

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .bluetooth import NinjaWoodfireClient
from .commands import CommandNotSupported
from .const import DOMAIN, NINJA_INDICATE_UUID, NINJA_NOTIFY_UUID, UPDATE_INTERVAL
from .protocol import NinjaState, apply_indicate, apply_notify

_LOGGER = logging.getLogger(__name__)

# Backoff constants (seconds)
_BACKOFF_INITIAL = 60
_BACKOFF_MAX = 300
_BACKOFF_MULTIPLIER = 2

# How long after the last received BLE packet we still consider the link
# "live". The device pushes data regularly, so if nothing arrives within this
# window the connection is treated as dead even if bleak still reports a link.
_DATA_STALE_AFTER = UPDATE_INTERVAL * 2


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
            hass=hass,
            address=address,
            on_data=self._on_ble_data,
            on_disconnect=self._on_disconnect,
        )
        self._connection_enabled: bool = True
        self._backoff: float = _BACKOFF_INITIAL
        self._reconnect_task: asyncio.Task | None = None
        # Monotonic timestamp of the last received BLE packet (0 = never).
        self._last_data_monotonic: float = 0.0

    @property
    def device_name(self) -> str:
        return self._device_name

    @property
    def address(self) -> str:
        return self._address

    @property
    def is_connection_live(self) -> bool:
        """True only when the BLE link is up AND data arrived recently.

        This is what the Connected sensor reflects: a real, communicating
        link. A bare BLE link with no recent packets (or a stale link that
        bleak has not yet noticed dropped) reports False.
        """
        if not self._client.is_connected:
            return False
        if not self._last_data_monotonic:
            return False
        return (time.monotonic() - self._last_data_monotonic) <= _DATA_STALE_AFTER

    async def async_start(self) -> None:
        """Connect the BLE client. Called once from __init__.py setup."""
        if not self._connection_enabled:
            return
        try:
            await self._client.start()
            self._backoff = _BACKOFF_INITIAL
            # Do NOT set connected=True here.  The BLE link is up but we have
            # not yet received any data from the device.  connected=True is set
            # in _on_ble_data once the device actually sends a notification or
            # indication, proving it is alive and communicating.
            self._state = NinjaState(
                raw_indicate=self._state.raw_indicate,
                raw_notify=self._state.raw_notify,
                connected=False,
            )
            self.async_set_updated_data(self._state)
            _LOGGER.debug("Connected to %s — waiting for first indication", self._address)
        except Exception as err:
            _LOGGER.warning(
                "Initial connection to %s failed: %s — will retry",
                self._address,
                err,
            )
            self._state = NinjaState(connected=False)
            self.async_set_updated_data(self._state)
            self._schedule_reconnect()

    async def async_stop(self) -> None:
        """Disconnect. Called from __init__.py unload."""
        self._connection_enabled = False
        if self._reconnect_task:
            self._reconnect_task.cancel()
            self._reconnect_task = None
        await self._client.stop()

    async def async_set_connected(self, enabled: bool) -> None:
        """Enable or disable the BLE connection (Connected switch)."""
        self._connection_enabled = enabled
        if enabled:
            if not self._client.is_connected:
                await self.async_start()
        else:
            if self._reconnect_task:
                self._reconnect_task.cancel()
                self._reconnect_task = None
            await self._client.stop()
            self._last_data_monotonic = 0.0
            self._state = NinjaState(
                **{**self._state.__dict__, "connected": False}
            )
            # Mark all entities unavailable
            self._mark_entities_unavailable()
            self.async_set_updated_data(self._state)

    def _mark_entities_unavailable(self) -> None:
        """Update state so all entities show unavailable."""
        self._state = NinjaState(
            raw_indicate=self._state.raw_indicate,
            raw_notify=self._state.raw_notify,
            connected=False,
        )

    @callback
    def _on_disconnect(self) -> None:
        """Handle unexpected BLE disconnect."""
        _LOGGER.warning("Unexpected disconnect from %s", self._address)
        self._last_data_monotonic = 0.0
        self._state = NinjaState(
            raw_indicate=self._state.raw_indicate,
            raw_notify=self._state.raw_notify,
            connected=False,
        )
        self.async_set_updated_data(self._state)

        if self._connection_enabled:
            self._schedule_reconnect()

    def _schedule_reconnect(self) -> None:
        """Schedule a reconnect attempt with exponential backoff."""
        if self._reconnect_task and not self._reconnect_task.done():
            return
        _LOGGER.debug(
            "Scheduling reconnect to %s in %.0f seconds",
            self._address,
            self._backoff,
        )
        self._reconnect_task = self.hass.async_create_task(
            self._reconnect_with_backoff()
        )

    async def _reconnect_with_backoff(self) -> None:
        """Wait and attempt reconnect, increasing backoff on failure."""
        await asyncio.sleep(self._backoff)
        if not self._connection_enabled:
            return
        try:
            await self._client.start()
            self._backoff = _BACKOFF_INITIAL
            # BLE link re-established — let _on_ble_data confirm connectivity
            # by setting connected=True when the first indication arrives.
            self._state = NinjaState(
                raw_indicate=self._state.raw_indicate,
                raw_notify=self._state.raw_notify,
                connected=False,
            )
            self.async_set_updated_data(self._state)
            _LOGGER.info("Reconnected to %s — waiting for first indication", self._address)
        except Exception as err:
            self._backoff = min(self._backoff * _BACKOFF_MULTIPLIER, _BACKOFF_MAX)
            _LOGGER.warning(
                "Reconnect to %s failed: %s — next attempt in %.0f s",
                self._address,
                err,
                self._backoff,
            )
            self._schedule_reconnect()

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
        self._last_data_monotonic = time.monotonic()
        self._state.connected = self.is_connection_live
        self.async_set_updated_data(self._state)

    async def async_send_command(self, builder: Callable[[], bytes]) -> bool:
        """Build a command payload and send it to the device.

        ``builder`` is one of the functions in ``commands.py``. Until the
        command format is confirmed those builders raise CommandNotSupported;
        we catch it here so control entities can be present in the UI without
        ever transmitting unverified bytes to a real appliance.
        """
        try:
            payload = builder()
        except CommandNotSupported as err:
            _LOGGER.warning(
                "Control command not sent to %s — %s", self._address, err
            )
            return False
        return await self._client.send_command(payload)

    async def _async_update_data(self) -> NinjaState:
        """Heartbeat — check connection health."""
        if not self._client.is_connected and self._connection_enabled:
            _LOGGER.debug("Heartbeat: not connected, scheduling reconnect")
            self._schedule_reconnect()
            raise UpdateFailed("Not connected")
        # Refresh the connectivity flag: the link can go stale (no packets)
        # even while bleak still reports it up. Reconnect if that happens.
        self._state.connected = self.is_connection_live
        if self._connection_enabled and not self._state.connected:
            _LOGGER.debug("Heartbeat: link stale, scheduling reconnect")
            self._schedule_reconnect()
        return self._state
