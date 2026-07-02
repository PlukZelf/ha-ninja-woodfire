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

# Callback the coordinator supplies: receives the two raw encrypted halves.
HalvesCallback = Callable[[bytes, bytes], None]


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
    """Recover the (20-byte, 23-byte) encrypted advert halves, or None."""
    # Primary: parse the full raw advertisement if available.
    raw = getattr(service_info, "raw", None)
    _LOGGER.warning("DEBUG: raw=%s (type=%s)", raw.hex() if raw else None, type(raw).__name__ if raw else None)
    if raw:
        payloads = list(_iter_manufacturer_payloads(bytes(raw)))
        by_len = {len(p): p for p in payloads}
        _LOGGER.warning("DEBUG: found payloads with lengths: %s", list(by_len.keys()))
        if HALF1_LEN in by_len and HALF2_LEN in by_len:
            _LOGGER.warning("DEBUG: both halves found in raw, returning")
            return by_len[HALF1_LEN], by_len[HALF2_LEN]
        _LOGGER.warning("DEBUG: raw parsed but missing one or both halves")

    # Fallback: manufacturer_data dict (may have dropped a half).
    md = service_info.manufacturer_data or {}
    _LOGGER.warning("DEBUG: manufacturer_data keys=%s", list(md.keys()))
    value = md.get(COMPANY_ID)
    _LOGGER.warning("DEBUG: COMPANY_ID 0x%04x value=%s (len=%d)", COMPANY_ID, value.hex() if value else None, len(value) if value else 0)
    if value is not None:
        if len(value) == HALF1_LEN + HALF2_LEN:  # 43: concatenated
            _LOGGER.warning("DEBUG: found 43-byte concatenated halves in manufacturer_data")
            return bytes(value[:HALF1_LEN]), bytes(value[HALF1_LEN:HALF1_LEN + HALF2_LEN])
        _LOGGER.warning(
            "DEBUG: Only one advert half available (len=%d) — waiting for a full packet",
            len(value),
        )
    _LOGGER.warning("DEBUG: extract_halves returning None")
    return None


class NinjaWoodfireScanner:
    """Registers a passive advertisement callback for one device."""

    def __init__(
        self,
        hass: HomeAssistant,
        address: str,
        on_halves: HalvesCallback,
    ) -> None:
        self._hass = hass
        self._address = address
        self._on_halves = on_halves
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
        if halves is None:
            return
        half1, half2 = halves
        self._on_halves(half1, half2)
