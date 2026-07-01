"""Time entities for Ninja Woodfire controls."""

from __future__ import annotations

from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import NinjaWoodfireConfigEntry
from . import commands
from .const import DOMAIN
from .coordinator import NinjaWoodfireCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NinjaWoodfireConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: NinjaWoodfireCoordinator = entry.runtime_data
    async_add_entities([NinjaWoodfireCookTime(coordinator)])


class NinjaWoodfireCookTime(CoordinatorEntity[NinjaWoodfireCoordinator], TimeEntity):
    """Cook duration as an HH:MM(:SS) time field.

    Only settable for Timed cooks. Defaults to 00:00:00.
    """

    _attr_has_entity_name = True
    _attr_name = "Cook Time"
    _attr_icon = "mdi:timer"

    def __init__(self, coordinator: NinjaWoodfireCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.address}_cook_time"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.address)},
            "name": coordinator.device_name,
            "manufacturer": "Ninja",
            "model": "Woodfire Pro",
        }
        # STUB: locally remembered value, used only while
        # commands.OPTIMISTIC_CONTROLS is True. See commands.py.
        self._optimistic_time: time | None = None

    @property
    def available(self) -> bool:
        # STUB: while optimistic, ignore connection state so the UI is usable
        # offline; only the cook-type gating applies. Remove once decoding works.
        if not commands.OPTIMISTIC_CONTROLS and not super().available:
            return False
        return self.coordinator.effective_cook_type == "Timed"

    @property
    def native_value(self) -> time | None:
        if commands.OPTIMISTIC_CONTROLS and self._optimistic_time is not None:
            return self._optimistic_time
        if self.coordinator.data is None:
            return time(0, 0, 0)
        total = self.coordinator.data.oven_time_set_s
        return time(hour=total // 3600, minute=(total % 3600) // 60, second=total % 60)

    async def async_set_value(self, value: time) -> None:
        # TEMPORARY: nothing is transmitted yet (see commands.OPTIMISTIC_CONTROLS).
        # Remember the value locally so the UI reflects it, then attempt the
        # (currently no-op) command. Remove the optimistic block once decoding works.
        minutes = value.hour * 60 + value.minute
        if commands.OPTIMISTIC_CONTROLS:
            self._optimistic_time = value
            self.async_write_ha_state()
        await self.coordinator.async_send_command(
            lambda: commands.set_cook_time(minutes)
        )
