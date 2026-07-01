"""Bluetooth client for the Ninja Woodfire integration."""

from __future__ import annotations

import logging
from collections.abc import Callable

from bleak import BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.exc import BleakError
from bleak_retry_connector import establish_connection
from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant

from .const import (
    NINJA_INDICATE_UUID,
    NINJA_NOTIFY_UUID,
    NINJA_SERVICE_UUID,
    NINJA_WRITE_UUID,
)
from .grillcore_native import get_native

_LOGGER = logging.getLogger(__name__)

NotifyCallback = Callable[[str, bytes], None]
DisconnectCallback = Callable[[], None]

REQUIRED_CHARACTERISTICS = {
    NINJA_WRITE_UUID,
    NINJA_NOTIFY_UUID,
    NINJA_INDICATE_UUID,
}


class NinjaWoodfireClient:
    """Manages the BLE connection to a Ninja Woodfire device."""

    def __init__(
        self,
        hass: HomeAssistant,
        address: str,
        on_data: NotifyCallback,
        on_disconnect: DisconnectCallback | None = None,
        *,
        connection_timeout: float = 20.0,
    ) -> None:
        self._hass = hass
        self._address = address
        self._on_data = on_data
        self._on_disconnect = on_disconnect
        self._connection_timeout = connection_timeout
        self._client: BleakClient | None = None
        self._native = get_native()

    @property
    def is_connected(self) -> bool:
        return self._client is not None and self._client.is_connected

    async def start(self) -> None:
        """Connect, validate GATT structure, and subscribe to notifications."""
        _LOGGER.debug("Connecting to %s", self._address)
        ble_device = bluetooth.async_ble_device_from_address(
            self._hass, self._address, connectable=True
        )
        if ble_device is None:
            raise BleakError(
                f"Device {self._address} not found — not currently in range"
            )

        client = await establish_connection(
            BleakClient,
            ble_device,
            self._address,
            disconnected_callback=self._handle_disconnect,
            timeout=self._connection_timeout,
        )
        _LOGGER.debug("Connected to %s — validating GATT structure", self._address)

        if not await self._validate_gatt(client):
            _LOGGER.error(
                "GATT validation failed for %s — disconnecting immediately",
                self._address,
            )
            await client.disconnect()
            raise ValueError(f"GATT structure mismatch for {self._address}")

        self._client = client
        await self._subscribe(client)
        _LOGGER.debug("GATT validated and subscribed for %s", self._address)

    async def stop(self) -> None:
        """Disconnect gracefully."""
        if self._client and self._client.is_connected:
            try:
                await self._client.disconnect()
            except (BleakError, OSError) as err:
                _LOGGER.debug("Error during disconnect: %s", err)
        self._client = None

    async def _validate_gatt(self, client: BleakClient) -> bool:
        """Validate that expected service and characteristics are present.

        Per the security spec: if the GATT structure does not match,
        disconnect immediately, log the error, and process nothing.
        """
        services = client.services
        service_uuids = {s.uuid for s in services}

        if NINJA_SERVICE_UUID not in service_uuids:
            _LOGGER.error(
                "Ninja service UUID %s not found on %s — possible spoof or wrong device",
                NINJA_SERVICE_UUID,
                self._address,
            )
            return False

        all_characteristic_uuids: set[str] = set()
        for service in services:
            for char in service.characteristics:
                all_characteristic_uuids.add(char.uuid)

        missing = REQUIRED_CHARACTERISTICS - all_characteristic_uuids
        if missing:
            _LOGGER.error(
                "Missing required characteristics on %s: %s",
                self._address,
                missing,
            )
            return False

        return True

    async def _subscribe(self, client: BleakClient) -> None:
        for uuid in (NINJA_NOTIFY_UUID, NINJA_INDICATE_UUID):
            try:
                await client.start_notify(uuid, self._notification_handler)
                _LOGGER.debug("Subscribed to %s", uuid)
            except (BleakError, OSError) as err:
                _LOGGER.warning("Could not subscribe to %s: %s", uuid, err)

    async def send_command(self, payload: bytes) -> bool:
        """Encrypt and send a command payload to the write characteristic."""
        if not self._client or not self._client.is_connected:
            return False

        if self._native.available():
            encrypted = self._native.encrypt_data(payload, NINJA_WRITE_UUID)
            if encrypted:
                payload = encrypted
            else:
                _LOGGER.warning("Encryption failed — skipping command for safety")
                return False
        else:
            _LOGGER.warning(
                "Native library not available — cannot encrypt commands. "
                "Copy libgrillcore_android.so to custom_components/ninja_woodfire/lib/"
            )
            return False

        try:
            await self._client.write_gatt_char(
                NINJA_WRITE_UUID, bytearray(payload), response=True
            )
            return True
        except (BleakError, OSError) as err:
            _LOGGER.error("Failed to write command: %s", err)
            return False

    def _notification_handler(
        self,
        characteristic: BleakGATTCharacteristic,
        data: bytearray,
    ) -> None:
        uuid = characteristic.uuid
        raw = bytes(data)
        _LOGGER.debug(
            "Notification from %s: %d bytes",
            uuid,
            len(raw),
        )

        if self._native.available() and uuid == NINJA_INDICATE_UUID:
            decrypted = self._native.decrypt_data(raw, uuid)
            if decrypted:
                self._on_data(uuid, decrypted)
                return

        self._on_data(uuid, raw)

    def _handle_disconnect(self, _client: BleakClient) -> None:
        _LOGGER.warning("Disconnected from %s", self._address)
        self._client = None
        if self._on_disconnect:
            self._on_disconnect()
