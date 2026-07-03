"""Passive BLE advertisement listener for the Ninja Woodfire integration."""

from __future__ import annotations

import logging
from collections.abc import Callable

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import (
    BluetoothCallbackMatcher,
    BluetoothChange,
    BluetoothServiceInfoBleak,
)
from homeassistant.core import HomeAssistant, callback

_LOGGER = logging.getLogger(__name__)

# The grill's two manufacturer-data AD structures share this company id.
COMPANY_ID = 0x0C4F
HALF1_LEN = 20
HALF2_LEN = 23

# Callbacks the coordinator supplies
HalvesCallback = Callable[[bytes, bytes], None]
SingleHalfCallback = Callable[[bytes], None]


def _iter_manufacturer_payloads(raw: bytes):
    """Yield manufacturer-specific-data payloads (bytes AFTER company id)
    for AD structures whose company id == COMPANY_ID, walking raw AD structs.
    """
    i = 0
    n = len(raw)
    while i < n:
        length = raw[i]
        if length == 0:
            break
        ad_type = raw[i + 1] if i + 1 < n else None
        ad_data = raw[i + 2 : i + 1 + length]  # length counts type + data
        if ad_type == 0xFF and len(ad_data) >= 2:
            company = int.from_bytes(ad_data[:2], "little")
            if company == COMPANY_ID:
                yield ad_data[2:]
        i += 1 + length


def extract_halves(service_info: BluetoothServiceInfoBleak) -> tuple[bytes, bytes] | None:
    """Recover the (20-byte, 23-byte) encrypted advert halves, or None if incomplete."""
    raw = getattr(service_info, "raw", None)
    if raw:
        payloads = list(_iter_manufacturer_payloads(bytes(raw)))
        by_len = {len(p): p for p in payloads}
        if HALF1_LEN in by_len and HALF2_LEN in by_len:
            return by_len[HALF1_LEN], by_len[HALF2_LEN]

    # Fallback: manufacturer_data dict
    md = service_info.manufacturer_data or {}
    value = md.get(COMPANY_ID)
    if value is not None and len(value) == HALF1_LEN + HALF2_LEN:
        return bytes(value[:HALF1_LEN]), bytes(value[HALF1_LEN:HALF1_LEN + HALF2_LEN])

    return None


def extract_single_half(service_info: BluetoothServiceInfoBleak) -> bytes | None:
    """
    Extract a single manufacturer-data half (20 or 23 bytes) if available.
    Used when the complete dual-half packet isn't present.
    """
    raw = getattr(service_info, "raw", None)
    if raw:
        payloads = list(_iter_manufacturer_payloads(bytes(raw)))
        for p in payloads:
            if len(p) in (HALF1_LEN, HALF2_LEN):
                return p

    # Fallback: manufacturer_data dict
    md = service_info.manufacturer_data or {}
    value = md.get(COMPANY_ID)
    if value is not None and len(value) in (HALF1_LEN, HALF2_LEN):
        return bytes(value)

    return None


class NinjaWoodfireScanner:
    """Registers a passive advertisement callback for one device."""

    def __init__(
        self,
        hass: HomeAssistant,
        address: str,
        on_halves: HalvesCallback,
        on_single_half: SingleHalfCallback | None = None,
    ) -> None:
        self._hass = hass
        self._address = address
        self._on_halves = on_halves
        self._on_single_half = on_single_half
        self._unregister: Callable[[], None] | None = None

    def start(self) -> None:
        """Register the passive callback. Idempotent."""
        if self._unregister is not None:
            return
        matcher = BluetoothCallbackMatcher(address=self._address)
        self._unregister = bluetooth.async_register_callback(
            self._hass,
            self._handle_advert,
            matcher,
            bluetooth.BluetoothScanningMode.PASSIVE,
        )
        _LOGGER.debug("Registered passive advert callback for %s", self._address)

    def stop(self) -> None:
        """Unregister the callback."""
        if self._unregister is not None:
            self._unregister()
            self._unregister = None

    @callback
    def _handle_advert(
        self,
        service_info: BluetoothServiceInfoBleak,
        change: BluetoothChange,
    ) -> None:
        halves = extract_halves(service_info)
        if halves is not None:
            half1, half2 = halves
            self._on_halves(half1, half2)
            return

        # Try single half if callback is registered
        if self._on_single_half is not None:
            single = extract_single_half(service_info)
            if single is not None:
                self._on_single_half(single)
