"""Diagnostics support for Ninja Woodfire (passive advert mode)."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from . import NinjaWoodfireConfigEntry
from .advert_decode import decode as decode_fields
from .coordinator import NinjaWoodfireCoordinator


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: NinjaWoodfireConfigEntry,
) -> dict[str, Any]:
    coordinator: NinjaWoodfireCoordinator = entry.runtime_data
    state = coordinator.data

    if state is None:
        return {"error": "No data available yet"}

    # state.raw_indicate holds the decoded 43-byte plaintext; raw_notify holds
    # the raw encrypted halves (half1 || half2), see advert.build_state_from_halves.
    decoded_fields: dict[str, Any] | None = None
    if state.raw_indicate and len(state.raw_indicate) == 43:
        decoded_fields = decode_fields(state.raw_indicate)

    return {
        "recently_seen": coordinator.is_recently_seen,
        "connected": state.connected,
        "raw_encrypted_hex": state.raw_notify.hex(" ") if state.raw_notify else None,
        "raw_encrypted_len": len(state.raw_notify),
        "decoded_plaintext_hex": state.raw_indicate.hex(" ") if state.raw_indicate else None,
        "decoded_plaintext_len": len(state.raw_indicate),
        "decoded_fields": decoded_fields,
        "parsed": {
            "cook_mode": state.cook_mode,
            "oven_current_temp_c": state.oven_current_temp_c,
            "oven_desired_temp_c": state.oven_desired_temp_c,
            "oven_time_left_s": state.oven_time_left_s,
            "oven_time_set_s": state.oven_time_set_s,
            "probe1": vars(state.probe1),
            "probe2": vars(state.probe2),
            "probe_temp_c": state.probe_temp_c,
        },
    }
