"""Bluetooth client for the Ninja Woodfire integration.

Handles connecting to the device, subscribing to notify/indicate
characteristics, and calling back into the coordinator when new
data arrives. Uses the native libgrillcore_android.so for
decryption when available, otherwise queues raw payloads for
future protocol implementation.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from bleak import BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.exc import BleakError

from .const import (
    NINJA_INDICATE_UUID,
    NINJA_NOTIFY_UUID,
    NINJA_WRITE_UUID,
    NINJA_SERVICE_UUID,
)
from .grillcore_native import get_native

_LOGGER = logging.getLogger(__name__)

NotifyCallback = Callable[[str, bytes], None]


class NinjaWoodfireClient:
    """Manages the BLE connection to a Ninja Woodfire device."""

    def __init__(
        self,
        address: str,
        on_data: NotifyCallback,
        *,
        connection_timeout: float = 20.0,
    ) -> None:
        self._address = address
        self._on_data = on_data
        self._connection_timeout = connection_timeout
        self._client: BleakClient | None = None
        self._native = get_native()
        self._session_id: int | None = None

    @property
    def is_connected(self) -> bool:
        return self._client is not None and self._client.is_connected

    async def start(self) -> None:
        """Connect to the device and subscribe to notifications."""
        _LOGGER.debug("Connecting to %s", self._address)
        client = BleakClient(
            self._address,
            disconnected_callback=self._on_disconnected,
            timeout=self._connection_timeout,
        )
        await client.connect()
        self._client = client
        _LOGGER.debug("Connected to %s", self._address)
        await self._subscribe(client)

    async def stop(self) -> None:
        """Disconnect gracefully."""
        if self._client and self._client.is_connected:
            try:
                await self._client.disconnect()
            except (BleakError, OSError) as err:
                _LOGGER.debug("Error during disconnect: %s", err)
        self._client = None

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

        # Encrypt via native library if available
        if self._native.available():
            encrypted = self._native.encrypt_data(payload, self._address)
            if encrypted:
                payload = encrypted
            else:
                _LOGGER.warning("Encryption failed, sending unencrypted — skipping for safety")
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
            "Notification from %s: %d bytes: %s",
            uuid,
            len(raw),
            raw.hex(" "),
        )

        # Try to decrypt via native library
        if self._native.available() and uuid == NINJA_INDICATE_UUID:
            decrypted = self._native.decrypt_data(raw, self._address)
            if decrypted:
                _LOGGER.debug("Decrypted: %s", decrypted.hex(" "))
                self._on_data(uuid, decrypted)
                return
            else:
                # First indication may be a challenge — pass raw for session setup
                _LOGGER.debug("Decrypt returned None (challenge packet?), passing raw")

        self._on_data(uuid, raw)

    def _on_disconnected(self, _client: BleakClient) -> None:
        _LOGGER.warning("Disconnected from %s", self._address)
        self._client = None
        self._session_id = None
