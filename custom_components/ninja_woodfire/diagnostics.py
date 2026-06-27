"""Diagnostics support for Ninja Woodfire Pro Connect XL.

Exposes raw BLE payloads and parsed state so that users can share
diagnostic information without exposing personal identifiers.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from . import NinjaWoodfireConfigEntry
from .coordinator import NinjaWoodfireCoordinator


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: NinjaWoodfireConfigEntry,
) -> dict[str, Any]:
    coordinator: NinjaWoodfireCoordinator = entry.runtime_data
    state = coordinator.data

    if state is None:
        return {"error": "No data available yet"}

    return {
        "connected": state.connected,
        "raw_indicate_hex": state.raw_indicate.hex(" ") if state.raw_indicate else None,
        "raw_indicate_len": len(state.raw_indicate),
        "raw_notify_hex": state.raw_notify.hex(" ") if state.raw_notify else None,
        "raw_notify_len": len(state.raw_notify),
        "parsed": {
            "power_on": state.power_on,
            "cooking_mode": state.cooking_mode,
            "target_temp_c": state.target_temp_c,
            "probe_temp_c": state.probe_temp_c,
            "timer_remaining_s": state.timer_remaining_s,
            "error_code": state.error_code,
        },
    }
